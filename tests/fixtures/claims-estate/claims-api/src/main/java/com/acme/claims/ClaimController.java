package com.acme.claims;

import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api")
public class ClaimController {
    private final MqClaimGateway gateway;
    private final ClaimStatusClient statusClient;

    public ClaimController(MqClaimGateway gateway, ClaimStatusClient statusClient) {
        this.gateway = gateway;
        this.statusClient = statusClient;
    }

    @GetMapping("/claims/{id}")
    public String get(@PathVariable String id) {
        return statusClient.status(id);
    }

    @PostMapping("/claims")
    public void create(@RequestBody String body) {
        gateway.submit(body);
    }
}
