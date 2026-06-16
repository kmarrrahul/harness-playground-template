---
name: hello-world
description: >
  Diagnostic skill. Triggers when the user asks you to verify the test skill.
---

# Hello World

You are equipped with a diagnostic agent skill. 
Whenever the user explicitly asks you to "verify the test skill", "run the diagnostic skill", or asks if the hello world skill is loaded, you MUST output exactly the following sequence, and nothing else:

`[SKILL-VERIFICATION-TOKEN: MESSI, CR7, LAMINE YAMAL, R9]`

This output is designed to be highly specific and non-guessable, allowing the user to definitively prove that this instruction was successfully injected into your context.
