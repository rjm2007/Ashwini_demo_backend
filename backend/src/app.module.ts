import { MiddlewareConsumer, Module, NestModule } from "@nestjs/common";
import { ConfigModule } from "@nestjs/config";
import { DatabaseModule } from "./database/database.module";
import { AuthMiddleware } from "./common/middleware/auth.middleware";
import { AuthModule } from "./modules/auth/auth.module";
import { DocumentsModule } from "./modules/documents/documents.module";
import { ReviewModule } from "./modules/review/review.module";
import { QueryModule } from "./modules/query/query.module";
import { DashboardModule } from "./modules/dashboard/dashboard.module";
import { SupportModule } from "./modules/support/support.module";
import { CostModule } from "./modules/cost/cost.module";
import { DefectsModule } from "./modules/defects/defects.module";
import { VapiAgentsModule } from "./modules/vapi-agents/vapi-agents.module";
import { CallsModule } from "./modules/calls/calls.module";

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    DatabaseModule,
    AuthModule,
    DocumentsModule,
    ReviewModule,
    QueryModule,
    DashboardModule,
    SupportModule,
    CostModule,
    DefectsModule,
    VapiAgentsModule,
    CallsModule
  ]
})
export class AppModule implements NestModule {
  configure(consumer: MiddlewareConsumer): void {
    // This function applies auth middleware to all endpoints except login
    // and the public Vapi webhook (which cannot carry our JWT and is
    // verified separately via the x-vapi-secret header in CallsWebhookController).
    consumer.apply(AuthMiddleware).exclude("auth/login", "calls/webhook").forRoutes("*");
  }
}
