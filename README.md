## Hi there 👋

<!--
**pini8151gz/pini8151gz** is a ✨ _special_ ✨ repository because its `README.md` (this file) appears on your GitHub profile.

Here are some ideas to get you started:

- 🔭 I’m currently working on ...
- 🌱 I’m currently learning ...
- 👯 I’m looking to collaborate on ...
- 🤔 I’m looking for help with ...
- 💬 Ask me about ...
- 📫 How to reach me: ...
- 😄 Pronouns: ...
- ⚡ Fun fact: ...
-->

## Venice MCP server

This repo ships a project-scoped MCP config (`.mcp.json`) that registers the
[Venice](https://venice.ai) MCP server for Claude Code.

Setup:

1. Export your Venice API key in your shell (or put it in a local `.env`, see `.env.example`):

   ```sh
   export VENICE_API_KEY=your-venice-api-key
   ```

2. Open this repo in Claude Code and approve the `venice` project MCP server when prompted.
3. Run `/mcp` to confirm the server is connected.

The key is read from the `VENICE_API_KEY` environment variable at startup, so it is never committed.
