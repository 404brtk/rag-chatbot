# Stage 1: Base stage with Bun for dependencies
FROM oven/bun:1.3.14-alpine AS base
WORKDIR /app
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Stage 2: Local development stage (reuses base, keeping Bun runtime)
FROM base AS dev
COPY . .
EXPOSE 5173
CMD ["bun", "run", "dev", "--host", "0.0.0.0"]

# Stage 3: Production builder stage (reuses base)
FROM base AS builder
COPY . .
RUN bun run build

# Stage 4: Production runner stage
FROM nginx:1.30.3-alpine AS runner
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
