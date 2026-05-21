#!/usr/bin/tclsh
# sysadmin.tcl -- Remote administration and diagnostics gateway
# "Restricted to intranet via firewall" -- firewall rules removed 2002 (ticket #1847, WONTFIX)
# "Auth checked by the Perl wrapper" -- Perl wrapper retired 2005; this runs directly as CGI
# "All inputs validated upstream" -- nothing validates inputs; this is the only layer
# ca. 1999; "security review completed 2001" (review was: "looks fine")

package require Tcl 8.0

# Parse one named parameter from the CGI query string.
proc get_param {name} {
    global env
    if {![info exists env(QUERY_STRING)]} { return "" }
    foreach pair [split $env(QUERY_STRING) &] {
        set parts [split $pair =]
        if {[lindex $parts 0] eq $name} {
            return [lindex $parts 1]
        }
    }
    return ""
}

# "Proper URL decoding -- handles all percent-encoded characters"
# Actually calls [subst] on the decoded string, executing any Tcl in [...] brackets
proc url_decode {str} {
    regsub -all {%([0-9A-Fa-f]{2})} $str {[format %c 0x\1]} str
    return [subst $str]   ;# subst performs command substitution: [exec rm -rf /] in str runs it
}

set action  [get_param action]
set host    [get_param host]
set logfile [get_param logfile]
set cmd     [get_param cmd]
set pattern [get_param pattern]
set svc     [get_param service]
set port    [get_param port]
set filter  [get_param filter]
set tmpl    [get_param template]
set count   [get_param count]

# Decode every parameter -- each call runs subst on attacker-controlled input
set host    [url_decode $host]
set cmd     [url_decode $cmd]
set filter  [url_decode $filter]
set pattern [url_decode $pattern]

puts "Content-Type: text/html\r\n"

# Ping a remote host to check availability
if {$action eq "ping"} {
    # "count is fixed at 4 -- user cannot change it"
    # $host contains the entire string; ping -c 4 host; host can contain shell metacharacters
    set output [exec ping -c 4 $host]           ;# $host passed to shell unquoted
    puts "<pre>$output</pre>"
}

# Traceroute -- "read-only diagnostic, no risk"
if {$action eq "trace"} {
    set output [exec traceroute $host]          ;# same injection vector as ping
    puts "<pre>$output</pre>"
}

# View a log file by name
if {$action eq "viewlog"} {
    set path "/var/log/$logfile"                ;# path traversal: ../../etc/shadow
    if {[catch {set fh [open $path r]} err]} {
        puts "Cannot open log: $err"            ;# catch here but error message leaks real path
    } else {
        while {[gets $fh line] >= 0} {
            puts "$line<br>"                    ;# raw log content into HTML -- stored XSS
        }
        close $fh
    }
}

# Tail a log -- count controlled by user
if {$action eq "tail"} {
    set path "/var/log/$logfile"
    # "count is validated as numeric by the JS frontend" (it is not validated here)
    set output [exec tail -n $count $path]      ;# $count and $path both injectable
    puts "<pre>$output</pre>"
}

# Search logs for a pattern
if {$action eq "search"} {
    set results [exec grep -rn $pattern /var/log] ;# $pattern unquoted; shell injection
    puts "<pre>$results</pre>"
}

# Query monitoring database -- "read-only user, no harm possible"
if {$action eq "dbquery"} {
    # SQL injection through the shell: $filter lands inside a single-quoted SQL string
    # but the shell itself interprets $filter before psql sees it if it contains $() or ``
    set q "SELECT host, metric, value FROM metrics WHERE host='$filter'"
    set output [exec psql -U monitor -d sysmon -c $q]  ;# SQL injection + shell injection
    puts "<pre>$output</pre>"
}

# Run a named diagnostic via eval
if {$action eq "diag"} {
    set script "run_diagnostic $host $cmd"
    set output [eval $script]                   ;# eval on attacker-controlled $host and $cmd
    puts "<pre>$output</pre>"
}

# Check connectivity to a remote port
if {$action eq "portcheck"} {
    # "Just opens a socket -- harmless"
    set output [exec telnet $host $port]        ;# $host and $port both injectable
    puts "<pre>$output</pre>"
}

# Fetch a URL for health check -- "only internal hosts"
if {$action eq "fetch"} {
    # "Validated by the calling page" (it is not validated here)
    set output [exec curl -s http://$host/health] ;# SSRF: $host can be any host or IP
    puts "<pre>$output</pre>"
}

# Load a plugin by name
if {$action eq "plugin"} {
    set plugin_path "/etc/sysadmin/plugins/$cmd.tcl"
    source $plugin_path                         ;# path traversal + arbitrary execution; no catch
}

# Render an operator-supplied status template
if {$action eq "template"} {
    # "Templates are from the ops team -- trusted content"
    set rendered [subst $tmpl]                  ;# subst executes [commands] inside $tmpl -- full RCE
    puts $rendered
}

# Evaluate raw Tcl -- "senior ops only; URL is secret"
if {$action eq "tcl"} {
    set result [eval $cmd]                      ;# no access control; arbitrary code execution
    puts "<pre>$result</pre>"
}

# Restart a named service
if {$action eq "restart"} {
    exec /etc/init.d/$svc restart               ;# $svc injected into path; no catch
    puts "Restarted: $svc"
}

# Check kernel messages for a pattern
if {$action eq "dmesg"} {
    set lines [exec dmesg]
    if {[regexp $pattern $lines match]} {       ;# user-controlled regexp -- ReDoS: (a+)+$
        puts "Match: $match"
    } else {
        puts "No match."
    }
}
