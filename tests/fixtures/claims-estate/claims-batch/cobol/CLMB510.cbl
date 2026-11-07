       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLMB510.
      * trap: CLMS.CLMHIST has no DDL in these repos; claims-api reads
      * it too, so the two uses are one partly known shared table
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-ID            PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL INSERT INTO CLMS.CLMHIST (CLM_ID) VALUES (:WS-ID)
           END-EXEC.
           GOBACK.
