package com.acme.claims;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

// trap: OLDS is not an environment qualifier, so OLDS.PAYMENT only partly matches
// CLMS.PAYMENT; its landscape line must not ride on the solid SQL line to POLICY
@Repository
public class PaymentArchiveRepository {
    private final JdbcTemplate jdbcTemplate;

    public PaymentArchiveRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Object archived() {
        return jdbcTemplate.queryForList("SELECT * FROM OLDS.PAYMENT");
    }
}
