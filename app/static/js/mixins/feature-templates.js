/** feature-templates.js — Curated prompt templates for each Harness Playground feature. */
/* eslint-disable no-undef */
const PROMPT_TEMPLATES = {
  /* PLAYGROUND — Generic workflows */
  playground: [
    {
      label: 'Debug Python Error',
      icon: '🐛',
      text: `I have a Python script that is throwing an error. Here is the script: \`test.py\`... [paste code here]. Can you help me debug it?`,
      hint: 'Basic debugging assistance',
    },
    {
      label: 'Generate Web UI',
      icon: '🎨',
      text: `I want to build a modern dashboard UI using HTML, Tailwind, and Alpine.js. Can you write the initial code for it?`,
      hint: 'Generate modern UI code',
    },
    {
      label: 'GitHub Repository Analysis',
      icon: '🐙',
      text: `Clone my repository from https://github.com/my-org/my-repo and summarize the architecture. Note: you may need my GitHub PAT to access it.`,
      hint: 'Analyze a GitHub repository',
    },
    {
      label: 'System Architecture Diagram',
      icon: '🏗️',
      text: `Can you create a system architecture diagram for a microservices e-commerce application? Use Mermaid.js.`,
      hint: 'Generate architecture diagrams',
      diagram: true,
    },
  ],
};
