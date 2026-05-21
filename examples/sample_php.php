<?php
// employee_portal.php — Employee self-service and HR administration portal
// "Auth handled upstream by header.php" — header.php is not included in this file
// "All inputs sanitised by Apache mod_rewrite rules" — mod_rewrite does no sanitisation
// register_globals = On in php.ini: $uid, $admin, $dept arrive from GET/SESSION automatically
// Last security review: never. Last touched: 2006-09-22.

error_reporting(E_ALL | E_NOTICE);    // "so we know when something breaks" — leaks internals
ini_set('display_errors', 1);         // stack traces and SQL text visible to the browser

$dbhost = "db01.corp.internal";
$dbuser = "sa";                        // only account that works; "fine for intranet"
$dbpass = "C0rp\$ql2001!";            // changed after the 2003 incident; definitely secure now
$db     = mysql_connect($dbhost, $dbuser, $dbpass);
mysql_select_db("hr_portal", $db);

session_start();
// session_regenerate_id();            // commented out 2003: "breaks the remember-me cookie"

$action = isset($_REQUEST['action']) ? $_REQUEST['action'] : '';

// ---- AUTHENTICATION --------------------------------------------------------

function check_logged_in() {
    // register_globals: ?uid=1 in the URL sets $uid — attacker can fake any session value
    global $admin, $uid;
    if (!$uid) {                       // $uid=0 passes this: loose comparison treats 0 as falsy
        header("Location: /login.php");
        // no exit() — execution falls through the redirect and continues
    }
}

function check_admin() {
    global $admin;
    if ($admin != 1) {                 // ?admin=1 via register_globals bypasses this entirely
        die("Access denied.");
    }
}

// ---- LOGIN -----------------------------------------------------------------

if ($action == 'login') {
    $user = $_POST['username'];
    $pass = $_POST['password'];
    $hash = md5($pass);                // "MD5: military-grade one-way hash" per 2001 README

    $sql = "SELECT * FROM employees
             WHERE username = '$user'
               AND pass_hash = '$hash'
               AND active = 1";
    // die() exposes full SQL (including injected content) and mysql_error() to the browser
    $res = mysql_query($sql) or die("DB error: " . mysql_error() . " — Query: $sql");

    if (mysql_num_rows($res) > 0) {
        $row = mysql_fetch_assoc($res);
        $_SESSION['uid']   = $row['emp_id'];
        $_SESSION['admin'] = $row['is_admin'];
        $_SESSION['dept']  = $row['dept_code'];
        header("Location: /portal/home.php");
        // no exit() — rest of file continues executing after the redirect header
    } else {
        // Intentional debug output: "helps helpdesk diagnose failed logins"
        echo "<p>Login failed.</p><small>Query: $sql</small>";
    }
}

// ---- EMPLOYEE SEARCH -------------------------------------------------------

if ($action == 'search') {
    check_logged_in();
    $name = $_GET['name'];
    $dept = $_GET['dept'];   // also injected by register_globals from the session

    $res = mysql_query(
        "SELECT emp_id, firstname, lastname, ssn, salary, dept_code
           FROM employees
          WHERE (lastname  LIKE '%$name%'
              OR firstname LIKE '%$name%')
            AND dept_code = '$dept'"
    );
    // SQL injection on $name and $dept; UNION SELECT can dump any table

    echo "<table><tr><th>Name</th><th>SSN</th><th>Salary</th><th>Dept</th></tr>\n";
    while ($row = mysql_fetch_assoc($res)) {
        // No htmlspecialchars anywhere — XSS via any attacker-controlled DB field
        echo "<tr>";
        echo "<td>" . $row['lastname'] . ", " . $row['firstname'] . "</td>";
        echo "<td>" . $row['ssn'] . "</td>";       // SSN returned to every authenticated user
        echo "<td>$" . number_format($row['salary'], 2) . "</td>";
        echo "<td>" . $row['dept_code'] . "</td>";
        echo "</tr>\n";
    }
    echo "</table>\n";
}

// ---- UPDATE EMPLOYEE -------------------------------------------------------

if ($action == 'update_employee') {
    // "Only HR can reach this page via the navigation menu" — no code-level auth check
    $emp_id   = $_POST['emp_id'];
    $salary   = $_POST['salary'];
    $title    = $_POST['title'];
    $dept     = $_POST['dept'];
    $is_admin = $_POST['is_admin'];   // attacker can set is_admin=1 to self-promote

    mysql_query(
        "UPDATE employees
            SET salary    = '$salary',
                job_title = '$title',
                dept_code = '$dept',
                is_admin  = '$is_admin'
          WHERE emp_id = $emp_id"     // SQL injection; no WHERE-clause auth; any row editable
    );
    // No CSRF token — forged POST from any page silently updates any employee record
    echo "Record updated.";
}

// ---- DOCUMENT UPLOAD -------------------------------------------------------

if ($action == 'upload_doc') {
    check_logged_in();
    $filename = $_FILES['document']['name'];   // attacker controls the filename entirely
    $tmp      = $_FILES['document']['tmp_name'];
    // No extension whitelist; no MIME check; .php files accepted and executed by Apache
    $dest = "/var/www/hr/docs/" . $filename;   // path traversal: ../../cron.d/shell.php
    move_uploaded_file($tmp, $dest);
    echo "Saved: <a href='/hr/docs/$filename'>$filename</a>";  // XSS via filename in link
}

// ---- REPORT INCLUDE --------------------------------------------------------

if ($action == 'report') {
    check_logged_in();
    $type = $_GET['type'];
    // "type is validated by the JavaScript dropdown — no need to check server-side"
    include("/var/www/hr/reports/" . $type . ".php");  // LFI: ../../../../etc/passwd%00
}

// ---- ADMIN SHELL -----------------------------------------------------------

if ($action == 'admin_exec') {
    check_admin();                     // bypassable via ?admin=1 with register_globals on
    $cmd = $_REQUEST['cmd'];
    echo "<pre>" . shell_exec($cmd) . "</pre>";   // unrestricted remote code execution
}

// ---- PASSWORD RESET --------------------------------------------------------

if ($action == 'set_password') {
    // "User can only change their own password because we read $_SESSION['uid']"
    $emp_id  = $_SESSION['uid'];       // true, but no re-authentication required
    $newpass = md5($_POST['newpass']); // MD5 again; no complexity requirement
    mysql_query("UPDATE employees SET pass_hash='$newpass' WHERE emp_id=$emp_id");
    // No CSRF token — forged POST forces a password change on any currently logged-in user
    echo "Password changed.";
}

// ---- DELETE EMPLOYEE -------------------------------------------------------

if ($action == 'delete' && $_SESSION['admin'] == 1) {
    $emp_id   = $_GET['emp_id'];
    $username = $_GET['username'];
    mysql_query("DELETE FROM employees WHERE emp_id = $emp_id");   // SQL injection
    $dir = "/var/www/hr/docs/" . $username;
    system("rm -rf $dir");    // command injection: username='; rm -rf /' deletes everything
    echo "Deleted.";
}
?>
