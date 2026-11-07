package com.acme.claims;

import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Component;

@Component
public class AuditPublisher {
    private final JmsTemplate jmsTemplate;

    public AuditPublisher(JmsTemplate jmsTemplate) {
        this.jmsTemplate = jmsTemplate;
    }

    public void publish(String event) {
        jmsTemplate.convertAndSend("CLM.AUDIT", event);
    }
}
