FROM node:20-alpine

WORKDIR /app

# Install deps first (better caching)
COPY package.json package-lock.json* ./
RUN npm ci

COPY . ./

EXPOSE 5173

# Default values work locally; docker-compose overrides VITE_HOST/PROXY_TARGET.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
