package com.acme.claims;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

// trap: CLMS.CLMHIST has no DDL in these repos (claims-batch CLMB510 writes it)
@Repository
public class ClaimHistoryRepository {
    private final JdbcTemplate jdbcTemplate;

    public ClaimHistoryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Object history() {
        return jdbcTemplate.queryForList("SELECT CLM_ID FROM CLMS.CLMHIST");
    }
}
