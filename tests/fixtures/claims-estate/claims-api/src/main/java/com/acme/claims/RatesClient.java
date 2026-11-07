package com.acme.claims;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

@Component
public class RatesClient {
    private final RestTemplate restTemplate = new RestTemplate();

    public String rates() {
        return restTemplate.getForObject("https://rates.example.com/v1/rates", String.class);
    }
}
