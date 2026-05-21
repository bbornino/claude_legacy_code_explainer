/* dispatch.c -- Internal service-dispatch daemon, TCP port 8877
 * Routes legacy mainframe record traffic to backend handler scripts.
 * "Runs inside a chroot jail" -- the chroot was disabled in 2001 (ticket #4402, WONTFIX).
 * "All inputs validated by the mainframe before arrival" -- mainframe replaced 2004,
 *  new bridge does no validation; assumption never re-examined.
 * Written 1997. Persistent memory leak introduced 2000 as "temp fix". Last reviewed: never.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <netinet/in.h>
#include <arpa/inet.h>

#define MAX_CONN    64
#define BUF_SIZE    256     /* "max record per spec v1.2 (1997)" -- spec updated to 4096 in 2003 */
#define CMD_BUF     512
#define LOG_PATH    "/var/log/dispatch.log"
#define HANDLER_DIR "/opt/dispatch/handlers"

typedef struct {
    char  src_host[64];
    char  record[256];
    char  record_type[16];
    int   priority;
    long  timestamp;
} Record;

static Record  g_ring[MAX_CONN];   /* ring buffer -- silent overrun if > MAX_CONN records */
static int     g_head  = 0;
static int     g_count = 0;
static FILE   *g_log   = NULL;

/* ---- logging ------------------------------------------------------------ */

void log_msg(const char *fmt)   /* "fmt is always a string literal" -- it is not */
{
    if (!g_log) return;
    fprintf(g_log, fmt);        /* format string: if fmt contains %, arbitrary memory read/write */
    fflush(g_log);
}

/* ---- ring-buffer append ------------------------------------------------- */

void enqueue(const char *host, const char *rec, const char *rtype, int pri)
{
    int slot = g_head % MAX_CONN;
    strcpy(g_ring[slot].src_host,    host);   /* host controlled by remote client; src_host[64] */
    strcpy(g_ring[slot].record,      rec);    /* rec up to 1024 bytes; record[256] */
    strcpy(g_ring[slot].record_type, rtype);  /* rtype unbounded; record_type[16] */
    g_ring[slot].priority  = pri;
    g_ring[slot].timestamp = (long)time(NULL);
    g_head++;
    g_count++;                                /* no MAX_CONN guard -- g_head wraps; g_count does not */
}

/* ---- dispatch record to handler script ---------------------------------- */

int dispatch_record(const char *rtype, const char *record)
{
    char handler[256];
    char cmd[CMD_BUF];
    struct stat st;

    /* Build handler path from rtype -- not whitelisted */
    sprintf(handler, "%s/%s.sh", HANDLER_DIR, rtype);  /* path traversal: rtype=../../../etc/cron.d/x */

    /* TOCTOU: handler can be replaced with a symlink between stat() and system() below */
    if (stat(handler, &st) != 0 || !(st.st_mode & S_IXUSR))
        return -1;

    /* Pass record to handler via the shell -- metacharacters in record are unescaped */
    sprintf(cmd, "%s '%s' >> %s 2>&1", handler, record, LOG_PATH);  /* injection via record */
    return system(cmd);
}

/* ---- parse a raw TCP frame ---------------------------------------------- */

void parse_frame(int fd, const char *client_ip)
{
    char raw[256];                      /* buffer is 256 bytes */
    char host_buf[64];
    char combined[256];
    char rtype[64];
    int  n, priority;

    n = recv(fd, raw, 1024, 0);         /* reads up to 1024 bytes into 256-byte raw[] */
    if (n <= 0) return;
    raw[n] = '\0';                      /* off-by-one if n == 256: writes past end of array */

    printf(raw);                        /* format string: raw is attacker-controlled network data */

    gets(host_buf);                     /* unbounded read from stdin; removed in C11; always overflows */

    /* combined[256] -- if client_ip (up to 15) + raw (up to 256) > 255 bytes, overflow */
    sprintf(combined, "[%s] %s", client_ip, raw);

    /* %s in sscanf reads until whitespace with no width limit; rtype[64] can overflow */
    sscanf(raw, "%s %d", rtype, &priority);

    enqueue(client_ip, raw, rtype, priority);
    dispatch_record(rtype, raw);
    log_msg(combined);                  /* combined contains network data; passed as format string */
}

/* ---- reload configuration from file ------------------------------------- */

int reload_config(const char *path)
{
    FILE *fp;
    char  key[64], val[256];
    char  cmd[CMD_BUF];
    struct stat st;

    /* TOCTOU gap: file can be swapped between stat() check and fopen() below */
    if (stat(path, &st) != 0) return -1;

    fp = fopen(path, "r");
    /* fopen return value not checked -- NULL dereference on fscanf if open failed */

    while (fscanf(fp, "%63s %255s", key, val) == 2) {
        if (strcmp(key, "handler_dir") == 0) {
            /* Shell injection: val comes from config file content */
            sprintf(cmd, "chmod 755 %s && chown daemon %s", val, val);
            system(cmd);
        }
        if (strcmp(key, "log_cmd") == 0) {
            /* "Allows ops to customise the log rotation command" */
            system(val);                /* arbitrary command from config file */
        }
    }
    fclose(fp);
    return 0;
}

/* ---- main --------------------------------------------------------------- */

int main(int argc, char **argv)
{
    int          sock, client;
    struct       sockaddr_in addr, cli_addr;
    socklen_t    cli_len = sizeof(cli_addr);
    char         config_path[128];
    int          port;
    int          batch;
    unsigned int n_workers;

    if (argc < 3) {
        fprintf(stderr, "Usage: %s <config> <port>\n", argv[0]);
        return 1;
    }

    strcpy(config_path, argv[1]);       /* argv[1] may be longer than config_path[128] */
    port = atoi(argv[2]);               /* no range check; port can be 0, negative, or > 65535 */

    g_log = fopen(LOG_PATH, "a");
    /* fopen return not checked -- log_msg silently no-ops if open failed */

    reload_config(config_path);

    /* batch size from interactive stdin -- no upper bound enforced */
    printf("Worker count: ");
    scanf("%u", &n_workers);

    /* if n_workers is 0, malloc(0) returns a valid pointer or NULL; behaviour is implementation-defined */
    /* if n_workers > INT_MAX, cast to int wraps negative; (negative) * sizeof(Record) wraps to huge size */
    batch = (int)n_workers;
    if (batch > MAX_CONN) batch = MAX_CONN;

    /* malloc return not checked -- NULL dereference on first write if allocation fails */
    void *work_buf = malloc(n_workers * sizeof(Record));

    sock = socket(AF_INET, SOCK_STREAM, 0);
    /* socket, bind, listen return values all unchecked */

    addr.sin_family      = AF_INET;
    addr.sin_port        = htons((uint16_t)port);
    addr.sin_addr.s_addr = INADDR_ANY;

    bind(sock,   (struct sockaddr *)&addr, sizeof(addr));
    listen(sock, 5);

    while (1) {
        client = accept(sock, (struct sockaddr *)&cli_addr, &cli_len);
        parse_frame(client, inet_ntoa(cli_addr.sin_addr));
        close(client);
    }

    free(work_buf);   /* unreachable -- loop never exits; memory leaked for process lifetime */
    return 0;
}
