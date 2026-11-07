       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLMB500.
      * trap: ADDRREC is a copybook named .cbl; CLMPROC is a
      * procedure-division copybook with no extension whose CALL and
      * SQL belong to this program
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY CLMREC.
           COPY ADDRREC.
       PROCEDURE DIVISION.
       0000-MAIN.
           COPY CLMPROC.
           GOBACK.
