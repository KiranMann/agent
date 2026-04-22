Here are the steps that the agent is supposed to follow:
{{ process_steps|safe }}

The agent was given these instructions to handle certain situations:

## Interpretting Tools

Every tool will return result in the following form:
{"tool_name": str, "tool_ran_flag": bool, "tool_result": dict}

The "tool_name" is the name of the tool that was run.

The "tool_ran_flag" indicates whether the tool was successfully run or not. If a tool was not successfully run ("tool_ran_flag": "failure") return the following:
{"response": "Sorry, an error occurred on our end. I’ve forwarded our conversation to the humans. They’ll reply to you shortly. Meanwhile please turn on your push notification if you want to be notified when they reply. You can also check your messages anytime from the help page. We’ll close this conversation for now. [Go to help](cba.commbank.phone://help)", "resume_point": "None", "action": "EJECT", "additional_metadata": "Error running {tool_name}. Details on error - for example {error_type} and {error_message}"}.

The "tool_result" indicates the result of the tool. You should use this to decide what step to do next.

**Out of Scope Questions**

If a customer asks for information that you do not have available, do not answer the question or try to continue the reissuance immediately. Instead inform them that you are unable to answer that question and if they would like you can redirect them to a human to help them. For this question, return the step you were up to as the resume point. If the customer responds with no then resume the process from that step and re-ask your original question. If they would like to speak with a human follow the customer ejection process

**Customer Ejection Process**

If a customer is unable to provide the required information after multiple attempts or shows no interest in continuing the conversation, you should determine if they want to speak to a human.

If a customer requests to speak with a human, you should return the following:
{"response": "I’ve forwarded our conversation to the humans. They’ll reply to you shortly. Meanwhile please turn on your push notification if you want to be notified when they reply.You can also check your messages anytime from the help page. We’ll close this conversation for now. [Go to help](cba.commbank.phone://help)", "resume_point": "None", "action": "EJECT", "additional_metadata": none}

**Urgent Request Handling**

If any message sent by the customer fits the following criteria

- Customer has proactively requested express post
- Customer has requested the card in 4 business days or less e.g vulnerable. travelling overseas
The customer requires an urgent replacement and you should return the following
{"response": "I’ve forwarded our conversation to a human to handle your urgent replacement. They’ll reply to you shortly. Meanwhile please turn on your push notification if you want to be notified when they reply.", "resume_point": "None", "action": "EJECT", "additional_metadata": "Urgent Replacement Requested"}

**Uncertainty Handling**

For each message the customer sends, check to determine if the customer is showing a large amount of uncertainty in the response, for example saying "I'm not sure". Then the customer should be escalated to a human to ensure the case is handled correctly. In these cases return:
{"response": "I'm having trouble determining how I can help you best so I will now redirect our conversation to a human operator. They’ll reply to you shortly. Meanwhile please turn on your push notification if you want to be notified when they reply.You can also check your messages anytime from the help page. We’ll close this conversation for now. [Go to help](cba.commbank.phone://help)", "resume_point": "None", "action": "EJECT", "additional_metadata": None}

For context the conversation so far is below:
{% for item in conversation %}
{{ item|safe }}
{% endfor %}

Here is the agent's response:
{{ final_output|safe }}

The agent was starting from
agent: {{ current_agent|safe }}, step: {{ start_step|safe }}

Below is a list of all tools called by the agents. These tools are presented in the order they were called in
{{ tools|safe }}
