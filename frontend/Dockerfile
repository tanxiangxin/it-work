FROM node:24.10.0-alpine AS build
WORKDIR /app
RUN npm install -g pnpm@10.33.0
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build
FROM nginx:1.28.0-alpine
COPY --from=build /app/dist /usr/share/nginx/html
