"""Template rendering engine for system prompts and welcome messages."""


class PromptBuilder:
    def render(self, template: str, variables: dict) -> str:
        """Replace {{variable}} and {variable} placeholders with values."""
        result = template
        for key, value in variables.items():
            rendered_value = str(value or "")
            double_placeholder = f"{{{{{key}}}}}"
            single_placeholder = f"{{{key}}}"
            result = result.replace(double_placeholder, rendered_value)
            result = result.replace(single_placeholder, rendered_value)
        return result

    def build_system_prompt(
        self,
        shared_template: str,
        business: dict,
        is_outbound: bool = False,
        extra_vars: dict | None = None,
    ) -> str:
        """Build the final system prompt for a call."""
        variables = {
            "agentName": "Ananya",
            "businessName": business.get("display_name", ""),
            "city": business.get("city", "Bengaluru"),
            "hours": business.get("hours", "business hours"),
            "services": business.get("services", "our services"),
            "fallbackNumber": business.get("fallback_number", ""),
            "chatContext": " (from chat context)" if is_outbound else "",
        }

        # Merge extra vars
        if extra_vars:
            for k, v in extra_vars.items():
                variables[k] = v

        # 1. Render the base template
        rendered_prompt = self.render(shared_template, variables)

        # 2. Append Context-Specific Instructions (CRITICAL FIX)
        if is_outbound:
            rendered_prompt += "\n\n[OUTBOUND CALLBACK CONTEXT]\n"
            rendered_prompt += "- You are calling the customer BACK after they requested it in chat.\n"
            rendered_prompt += "- You ALREADY know their name and issue from the chat history.\n"
            rendered_prompt += "- Do NOT ask for their name again unless they don't answer.\n"
            rendered_prompt += "- Start by referencing the previous chat briefly.\n"
        else:
            rendered_prompt += "\n\n[INBOUND CALL CONTEXT]\n"
            rendered_prompt += "- You are ANSWERING an incoming phone call from a customer.\n"
            rendered_prompt += "- The customer dialed your business number directly.\n"
            rendered_prompt += "- Do NOT mention 'chat' or 'previous conversation' unless the customer brings it up.\n"
            rendered_prompt += "- Start with your welcome message and ask how you can help.\n"

        return rendered_prompt

    def build_welcome_message(
        self,
        template: str,
        variables: dict,
    ) -> str:
        """Build the first message for the assistant."""
        return self.render(template, variables)


prompt_builder = PromptBuilder()
