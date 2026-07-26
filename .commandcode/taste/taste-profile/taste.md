# Taste Profile
- Provides raw terminal/log output as evidence when reporting issues, rather than paraphrasing or summarizing. Confidence: 1.0
- Uses very terse, informal, abbreviated language when asking about errors (e.g., "why this resolve" or "hey fiix thiis n" instead of full sentences). Confidence: 0.9
- Expects explicit verification/confirmation that file edits actually persisted and took effect, not just that they were attempted. Confidence: 0.7
- Does NOT want the assistant to run diagnostic shell/PowerShell/curl/Python commands on their machine. Instead, make the correct code changes and let the user test themselves. Confidence: 0.9
- Provides complete, copy-paste-ready code blocks when requesting changes, rather than describing changes in prose. Confidence: 0.8
- Prefers production-ready, robust code with defensive edge-case handling (timeout retries, cold-start handling, comprehensive intent/keyword lists, input sanitization). Confidence: 0.7
- Prefers cloud-hosted/serverless architecture over local development — wants to eliminate local dependencies entirely and offload work to cheap/free cloud services (e.g., Render Free, Apps Script, MongoDB Atlas). Confidence: 0.8
- Uses external uptime monitoring services (e.g., cron-job.org pinging every 10 minutes) to keep Render Free tier services awake and prevent cold-start sleep. Confidence: 0.8
- Aggressively configures services to stay within free-tier resource limits — uses lightweight engines (e.g., NOWEB instead of Puppeteer), caps Node heap via NODE_OPTIONS, and directs ephemeral file storage to /tmp to avoid RAM/disk blowouts on 512MB instances. Confidence: 0.7
