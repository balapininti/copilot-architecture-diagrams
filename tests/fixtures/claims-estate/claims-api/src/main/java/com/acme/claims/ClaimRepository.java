package com.acme.claims;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class ClaimRepository {
    private final JdbcTemplate jdbcTemplate;

    public ClaimRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Object find(String policyNo) {
        return jdbcTemplate.query("SELECT * FROM CLMS.POLICY WHERE POLICY_NO = ?",
                (rs, n) -> rs.getString(1), policyNo);
    }
}
