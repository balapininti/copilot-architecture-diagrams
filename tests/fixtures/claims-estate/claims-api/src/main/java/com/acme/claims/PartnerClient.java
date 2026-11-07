package com.acme.claims;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

// trap: a partner's service whose path happens to equal one of ours; the host is not
// named in any scanned repo's config, so a path-only match is not a confirmed link
@Component
public class PartnerClient {
    private final RestTemplate restTemplate = new RestTemplate();

    public String partnerClaim(String id) {
        return restTemplate.getForObject("https://partner.example.com/api/claims/{id}",
                String.class, id);
    }
}
