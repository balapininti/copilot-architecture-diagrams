package com.acme.claims;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class ClaimStatusClient {
    private final RestTemplate restTemplate;

    @Value("${zosconnect.url}")
    private String zosUrl;

    public ClaimStatusClient(RestTemplate restTemplate) {
        this.restTemplate = restTemplate;
    }

    public String status(String id) {
        return restTemplate.getForObject(zosUrl + "/zos/claims/{id}/status", String.class, id);
    }
}
