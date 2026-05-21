      *> claims.cbl -- Unemployment Claims Processing System
      *> State Department of Labor, Benefits Division
      *> Written 1986. DO NOT ALTER THE GOTO STRUCTURE -- tried in 1994; broke everything.
      *> Y2K patch applied 1999: ONLY the main claim date was fixed. See WS-SEP-DATE.
      *> "Fully tested" -- last full regression test was 1989.
      *> "Handles all separation reason codes" -- codes 15, 22, 31 silently fall through.

       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLAIMS-PROC.
       AUTHOR. W KOWALCZYK.
       DATE-WRITTEN. 1986-03-15.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CLAIM-FILE
               ASSIGN TO 'CLMFILE'.
           SELECT EMPLOYER-FILE
               ASSIGN TO 'EMPFILE'.
           SELECT BENEFIT-TABLE
               ASSIGN TO 'BENFIL'.
           SELECT PAYMENT-FILE
               ASSIGN TO 'PAYFIL'.
           SELECT EXCEPTION-FILE
               ASSIGN TO 'EXCFIL'.
           SELECT AUDIT-FILE
               ASSIGN TO 'AUDFIL'.

       DATA DIVISION.
       FILE SECTION.
       FD  CLAIM-FILE.
       01  CLAIM-REC.
           05  CLM-SSN            PIC 9(9).
           05  CLM-LAST-NAME      PIC X(20).
           05  CLM-FIRST-NAME     PIC X(15).
           05  CLM-HIRE-DATE      PIC 9(6).   *> YYMMDD -- Y2K patched: now treated as CCYYMMDD
           05  CLM-SEP-DATE       PIC 9(6).   *> YYMMDD -- Y2K NOT patched; 2000+ claimants wrong
           05  CLM-WEEKLY-WAGE    PIC 9(5)V99.*> implicit decimal; max $99,999.99; never documented
           05  CLM-REASON-CODE    PIC 9(2).
           05  CLM-WEEKS-CLAIMED  PIC 9(2).
           05  CLM-STATUS         PIC X.      *> P=pending A=approved D=denied X=fraud
           05  CLM-EMPLOYER-FEIN  PIC 9(9).

       FD  EMPLOYER-FILE.
       01  EMP-REC.
           05  EMP-FEIN           PIC 9(9).
           05  EMP-NAME           PIC X(30).
           05  EMP-RATE           PIC V9(4).  *> implicit contribution rate; e.g. V9(4)=.0350
           05  EMP-BALANCE        PIC S9(7)V99.
           05  EMP-STATUS         PIC X.

       FD  BENEFIT-TABLE.
       01  BEN-REC.
           05  BEN-REASON-CODE    PIC 9(2).
           05  BEN-PCT            PIC V99.    *> implicit decimal; .60 = 60%; max .99
           05  BEN-MAX-WEEKS      PIC 9(2).
           05  BEN-MAX-AMT        PIC 9(5)V99.

       FD  PAYMENT-FILE.
       01  PAY-REC                PIC X(132).

       FD  EXCEPTION-FILE.
       01  EXCPT-REC              PIC X(132).

       FD  AUDIT-FILE.
       01  AUDIT-REC              PIC X(200).

       WORKING-STORAGE SECTION.
       01  WS-FLAGS.
           05  WS-EOF-CLM         PIC X VALUE 'N'.
           05  WS-EOF-EMP         PIC X VALUE 'N'.
           05  WS-EOF-BEN         PIC X VALUE 'N'.
           05  WS-EMP-FOUND       PIC X VALUE 'N'.
           05  WS-BEN-FOUND       PIC X VALUE 'N'.
           05  WS-FRAUD-FLAG      PIC X VALUE 'N'.

       01  WS-ACCUM.
           05  WS-TOTAL-CLAIMS    PIC 9(5)    VALUE ZEROS. *> overflows silently at 100,000
           05  WS-TOTAL-PAID      PIC 9(9)V99 VALUE ZEROS.
           05  WS-DENIED-COUNT    PIC 9(4)    VALUE ZEROS.
           05  WS-DEPT-PAID       PIC 9(7)V99 VALUE ZEROS. *> accumulates across ALL depts; never reset
           05  WS-FRAUD-COUNT     PIC 9(3)    VALUE ZEROS. *> overflows at 1,000; wraps to 000

       01  WS-CALC.
           05  WS-BEN-AMT         PIC 9(5)V99.
           05  WS-TOTAL-BENEFIT   PIC 9(7)V99.
           05  WS-TAX-HELD        PIC 9(5)V99.
           05  WS-NET-BEN         PIC 9(5)V99.
           05  WS-SEP-YY          PIC 9(2).
           05  WS-HIRE-YY         PIC 9(2).
           05  WS-CUR-YY          PIC 9(2) VALUE 05. *> HARDCODED 2005 -- never updated since patch
           05  WS-TENURE-YRS      PIC 9(2).          *> goes negative for pre-2000 hires post-2000

       01  WS-REDEF-WAGE.
           05  WS-WAGE-PACKED     PIC 9(5)V99 COMP-3. *> packed decimal in memory
           05  WS-WAGE-DISPLAY    REDEFINES WS-WAGE-PACKED
                                  PIC X(4).           *> reinterprets packed bytes as text; garbage

       01  WS-DATE-WORK.
           05  WS-RUN-DATE        PIC X(8) VALUE '20051231'. *> hardcoded; overrides ACCEPT below
           05  WS-CUR-DATE-8      PIC 9(8).

       01  WS-OUT-LINE.
           05  WS-O-SSN           PIC 9(9).
           05  FILLER             PIC X VALUE SPACES.
           05  WS-O-NAME          PIC X(20).
           05  FILLER             PIC X VALUE SPACES.
           05  WS-O-GROSS         PIC ZZZ,ZZ9.99.
           05  FILLER             PIC X VALUE SPACES.
           05  WS-O-NET           PIC ZZZ,ZZ9.99.
           05  FILLER             PIC X VALUE SPACES.
           05  WS-O-WEEKS         PIC Z9.
           05  FILLER             PIC X VALUE SPACES.
           05  WS-O-STATUS        PIC X.

       01  WS-AUDIT-LINE.
           05  WS-AUD-SSN         PIC 9(9).
           05  FILLER             PIC X VALUE SPACES.
           05  WS-AUD-ACTION      PIC X(10).
           05  FILLER             PIC X VALUE SPACES.
           05  WS-AUD-AMT         PIC ZZZZ9.99.
           05  FILLER             PIC X VALUE SPACES.
           05  WS-AUD-DATE        PIC X(8).

       PROCEDURE DIVISION.
       0000-MAIN.
           OPEN INPUT  CLAIM-FILE
                       EMPLOYER-FILE
                       BENEFIT-TABLE
                OUTPUT PAYMENT-FILE
                       EXCEPTION-FILE
                       AUDIT-FILE.                *> no FILE STATUS -- open failure is silent

           ACCEPT WS-CUR-DATE-8 FROM DATE YYYYMMDD.
           *> WS-RUN-DATE hardcoded VALUE '20051231' above is what actually drives date arithmetic

           PERFORM 1000-INIT.

           READ CLAIM-FILE
               AT END MOVE 'Y' TO WS-EOF-CLM.    *> no FILE STATUS

           PERFORM 2000-PROCESS-CLAIM
               UNTIL WS-EOF-CLM = 'Y'.

           PERFORM 9000-WRAP-UP.
           STOP RUN.

       1000-INIT.
           MOVE ZEROS  TO WS-ACCUM.
           MOVE SPACES TO WS-OUT-LINE WS-AUDIT-LINE.

       2000-PROCESS-CLAIM.
           MOVE 'N' TO WS-EMP-FOUND WS-BEN-FOUND WS-FRAUD-FLAG.

           IF CLM-STATUS NOT = 'P'
               GO TO 2000-SKIP-CLAIM.             *> skips to write exception then falls to 2000-READ

           ADD 1 TO WS-TOTAL-CLAIMS.              *> PIC 9(5): wraps at 100,000 with no trap

      *    Detect fraud: separation before hire (Y2K unfixed in CLM-SEP-DATE)
           MOVE CLM-SEP-DATE  (1:2) TO WS-SEP-YY.
           MOVE CLM-HIRE-DATE (1:2) TO WS-HIRE-YY.
           COMPUTE WS-TENURE-YRS = WS-CUR-YY - WS-HIRE-YY. *> WS-CUR-YY hardcoded 05
           *> Pre-2000 hire + 20xx run = WS-HIRE-YY e.g. 97; 05 - 97 = -92 in PIC 9(2) = 08

           IF WS-TENURE-YRS < 0
               MOVE 'Y' TO WS-FRAUD-FLAG
               ADD 1 TO WS-FRAUD-COUNT            *> PIC 9(3): wraps at 1,000
               GO TO 2900-FRAUD-EXCEPT.

           IF WS-TENURE-YRS = 0
               MOVE 1 TO WS-TENURE-YRS.           *> same-year hire: silently assume 1 year

      *    Look up employer record by scanning the employer file sequentially
           PERFORM 3000-FIND-EMPLOYER
               UNTIL WS-EMP-FOUND = 'Y'
                  OR WS-EOF-EMP   = 'Y'.

           IF WS-EMP-FOUND = 'N'
               GO TO 2500-NO-EMPLOYER.

           PERFORM 4000-FIND-BENEFIT.

           IF WS-BEN-FOUND = 'N'
               MOVE 0.40 TO BEN-PCT               *> overwrites FD buffer -- poisons next read
               MOVE 26   TO BEN-MAX-WEEKS.

           PERFORM 5000-CALC-BENEFIT.
           PERFORM 6000-WRITE-PAYMENT.
           GO TO 2000-READ.

       2000-SKIP-CLAIM.
           MOVE CLM-SSN      TO WS-O-SSN.
           MOVE CLM-LAST-NAME TO WS-O-NAME.
           MOVE CLM-STATUS   TO WS-O-STATUS.
           WRITE EXCPT-REC FROM WS-OUT-LINE.       *> no FILE STATUS

       2500-NO-EMPLOYER.
           MOVE CLM-SSN      TO WS-AUD-SSN.
           MOVE 'NOEMP     ' TO WS-AUD-ACTION.
           MOVE WS-RUN-DATE  TO WS-AUD-DATE.       *> hardcoded date in audit trail
           WRITE AUDIT-REC FROM WS-AUDIT-LINE.
           GO TO 2000-READ.

       2900-FRAUD-EXCEPT.
           MOVE CLM-SSN      TO WS-O-SSN.
           MOVE CLM-LAST-NAME TO WS-O-NAME.
           MOVE WS-TENURE-YRS TO WS-O-WEEKS.      *> negative tenure into unsigned PIC Z9 field
           WRITE EXCPT-REC FROM WS-OUT-LINE.
           GO TO 2000-READ.

       2000-READ.
           READ CLAIM-FILE
               AT END MOVE 'Y' TO WS-EOF-CLM.     *> no FILE STATUS

       3000-FIND-EMPLOYER.
           READ EMPLOYER-FILE
               AT END MOVE 'Y' TO WS-EOF-EMP.     *> no FILE STATUS
           IF EMP-FEIN = CLM-SSN                  *> BUG: compares FEIN to SSN -- always false
               MOVE 'Y' TO WS-EMP-FOUND.
           *> Should be: IF EMP-FEIN = CLM-EMPLOYER-FEIN

       4000-FIND-BENEFIT.
           READ BENEFIT-TABLE
               AT END MOVE 'Y' TO WS-EOF-BEN.     *> no FILE STATUS
           IF BEN-REASON-CODE = CLM-REASON-CODE
               MOVE 'Y' TO WS-BEN-FOUND.

       5000-CALC-BENEFIT.
           COMPUTE WS-BEN-AMT =
               CLM-WEEKLY-WAGE * BEN-PCT.          *> BEN-PCT is V99: max .99 not 99%
           IF WS-BEN-AMT > BEN-MAX-AMT
               MOVE BEN-MAX-AMT TO WS-BEN-AMT.

           COMPUTE WS-TOTAL-BENEFIT =
               WS-BEN-AMT * CLM-WEEKS-CLAIMED.

           COMPUTE WS-TAX-HELD ROUNDED =
               WS-TOTAL-BENEFIT * 0.10.            *> flat 10% ignores actual federal tax tables
           COMPUTE WS-NET-BEN =
               WS-TOTAL-BENEFIT - WS-TAX-HELD.

           ADD WS-NET-BEN TO WS-TOTAL-PAID.
           ADD WS-NET-BEN TO WS-DEPT-PAID.         *> never reset between departments

       6000-WRITE-PAYMENT.
           MOVE CLM-SSN          TO WS-O-SSN.
           MOVE CLM-LAST-NAME    TO WS-O-NAME.
           MOVE WS-BEN-AMT       TO WS-O-GROSS.
           MOVE WS-NET-BEN       TO WS-O-NET.
           MOVE CLM-WEEKS-CLAIMED TO WS-O-WEEKS.
           MOVE 'A'              TO WS-O-STATUS.
           MOVE 'A'              TO CLM-STATUS.    *> updates working storage copy only, not the file
           WRITE PAY-REC FROM WS-OUT-LINE.         *> no FILE STATUS

       9000-WRAP-UP.
           CLOSE CLAIM-FILE
                 EMPLOYER-FILE
                 BENEFIT-TABLE
                 PAYMENT-FILE
                 EXCEPTION-FILE
                 AUDIT-FILE.
           DISPLAY 'CLAIMS PROCESSED: ' WS-TOTAL-CLAIMS.
           DISPLAY 'TOTAL PAID      : ' WS-TOTAL-PAID.
           DISPLAY 'DENIED          : ' WS-DENIED-COUNT.
           DISPLAY 'FRAUD EXCEPTIONS: ' WS-FRAUD-COUNT.
           DISPLAY 'RUN DATE        : ' WS-RUN-DATE.
