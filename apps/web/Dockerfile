FROM node:22-alpine

WORKDIR /app
ENV NODE_ENV=production

RUN npm config set registry https://mirrors.cloud.tencent.com/npm/

COPY package.json package-lock.json* ./
RUN npm ci --registry=https://mirrors.cloud.tencent.com/npm/

COPY . .
RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
