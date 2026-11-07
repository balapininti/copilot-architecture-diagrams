       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLMO140.
      * trap: MQ handles qualified with OF; two MQOPENs name different
      * queues, so a handle must be tied to its own MQOPEN
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  CTL.
           05  HCONN        PIC S9(9) BINARY.
           05  HAUD         PIC S9(9) BINARY.
           05  HRSP         PIC S9(9) BINARY.
       01  WS-HANDLE        PIC S9(9) BINARY.
       01  MQOD.
           05  MQOD-OBJECTNAME PIC X(48).
       01  OPTS             PIC S9(9) BINARY.
       01  CC               PIC S9(9) BINARY.
       01  RC               PIC S9(9) BINARY.
       PROCEDURE DIVISION.
       0000-MAIN.
           MOVE 'CLM.AUDIT' TO MQOD-OBJECTNAME
           CALL 'MQOPEN' USING HCONN OF CTL, MQOD, OPTS, HAUD OF CTL,
                CC, RC.
           MOVE 'CLM.RSP' TO MQOD-OBJECTNAME
           CALL 'MQOPEN' USING HCONN OF CTL, MQOD, OPTS, HRSP OF CTL,
                CC, RC.
           CALL 'MQPUT' USING HCONN OF CTL, HAUD OF CTL, MQOD, OPTS,
                CC, RC.
           CALL 'MQPUT' USING HCONN OF CTL, WS-HANDLE, MQOD, OPTS,
                CC, RC.
           GOBACK.
