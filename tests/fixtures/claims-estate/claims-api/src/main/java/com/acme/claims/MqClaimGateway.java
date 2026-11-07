package com.acme.claims;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.jms.core.JmsTemplate;
import org.springframework.stereotype.Component;

@Component
public class MqClaimGateway {
    @Value("${mq.request}")
    private String requestQueue;

    @Value("${mq.reply}")
    private String replyQueue;

    private final JmsTemplate jmsTemplate;

    public MqClaimGateway(JmsTemplate jmsTemplate) {
        this.jmsTemplate = jmsTemplate;
    }

    public void submit(String body) {
        jmsTemplate.convertAndSend(requestQueue, body);
    }

    public Object reply() {
        return jmsTemplate.receive(replyQueue);
    }
}
