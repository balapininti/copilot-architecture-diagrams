       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLMB300.
      *    Paiement de réclamation - accès aux données
       DATA DIVISION.
       WORKING-STORAGE SECTION.
           COPY PAYREC.
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO CLMS.PAYMENT (CLAIM_ID, AMOUNT)
               VALUES (:PAY-CLM-ID, :PAY-AMT)
           END-EXEC
           GOBACK.
