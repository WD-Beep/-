FROM node:22-alpine

WORKDIR /app

RUN npm config set registry https://mirrors.cloud.tencent.com/npm/

COPY package.json package-lock.json* ./
RUN npm install --registry=https://mirrors.cloud.tencent.com/npm/

COPY . .
RUN npm run build
ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "run", "start"]
