import { ValidationPipe } from "@nestjs/common";
import { NestFactory } from "@nestjs/core";
import { AppModule } from "./app.module";
import { json } from "express";

/**
 * Browser origins allowed to call this API.
 *
 * FRONTEND_URL may hold a comma-separated list (local dev plus the deployed
 * frontend). When it is unset the previous wide-open behaviour is kept, so
 * that an environment which has not been updated yet does not suddenly break —
 * but that is logged loudly, because `enableCors()` with no options emits
 * `Access-Control-Allow-Origin: *` and lets any site on the internet call
 * this API.
 */
function resolveCorsOrigins(): string[] | true {
  const configured = (process.env.FRONTEND_URL || "")
    .split(",")
    .map((o) => o.trim())
    .filter(Boolean);

  if (configured.length === 0) {
    // eslint-disable-next-line no-console
    console.warn(
      "[cors] FRONTEND_URL is not set — allowing all origins. Set FRONTEND_URL " +
        "to the frontend's URL (comma-separated for more than one) to lock this down."
    );
    return true;
  }
  return configured;
}

async function bootstrap() {
  // This function starts the API server with global validation and CORS.
  const app = await NestFactory.create(AppModule);
  app.enableCors({ origin: resolveCorsOrigins(), credentials: true });
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
