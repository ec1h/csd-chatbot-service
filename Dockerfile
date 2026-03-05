FROM node:20-slim AS builder

WORKDIR /app

# Copy package files
COPY package*.json ./
RUN npm ci --only=production

# Production stage
FROM node:20-slim

WORKDIR /app

# Install Python for the classification pipeline
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r chatbot && useradd -r -g chatbot chatbot

# Copy node modules from builder
COPY --from=builder --chown=chatbot:chatbot /app/node_modules ./node_modules

# Copy application code
COPY --chown=chatbot:chatbot . .

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Change ownership
RUN chown -R chatbot:chatbot /app

# Switch to non-root user
USER chatbot

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8001/health', (r) => r.statusCode === 200 ? process.exit(0) : process.exit(1))" || exit 1

EXPOSE 8001

CMD ["node", "server.js"]