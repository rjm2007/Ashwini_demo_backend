import { ValidationPipe } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { AppModule } from "./app.module";
import { json } from "express";

async function bootstrap() {
  // This function starts the API server with global validation and CORS.
  const app = await NestFactory.create(AppModule);
  app.enableCors();
  app.use(json({ limit: "20mb" }));
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      transform: true,
      forbidNonWhitelisted: true
    })
  );
  const port = Number(process.env.BACKEND_PORT || 3001);
  await app.listen(port);
}

bootstrap();
