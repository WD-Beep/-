FROM node:22-alpine

WORKDIR /app

ARG NPM_REGISTRY=https://registry.npmjs.org/
RUN npm config set registry ${NPM_REGISTRY}

COPY package.json package-lock.json* ./
RUN npm install --registry=${NPM_REGISTRY}

COPY . .
ARG INTERNAL_API_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_API_URL=/api-proxy
ARG NEXT_PUBLIC_LONG_RUNNING_API_URL=/api-long
ENV INTERNAL_API_URL=${INTERNAL_API_URL}
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_PUBLIC_LONG_RUNNING_API_URL=${NEXT_PUBLIC_LONG_RUNNING_API_URL}
RUN npm run build
ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start"]
