import { Body, Controller, Delete, Get, Param, Post, Put, Req, UseGuards } from "@nestjs/common";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { AppSettingsService } from "./app-settings.service";
import { SetApiKeyDto, TestApiKeyDto } from "./dto/set-api-key.dto";

/**
 * Admin-only. Every route here reads or writes provider credentials, so none
 * of them may widen past UserRole.ADMIN. Reads return masked previews only —
 * there is deliberately no endpoint that hands back a usable secret.
 */
@Controller("app-settings/api-keys")
@UseGuards(RolesGuard)
@Roles(UserRole.ADMIN)
export class AppSettingsController {
  constructor(private readonly appSettingsService: AppSettingsService) {}

  @Get()
  @Roles(UserRole.ADMIN)
  list() {
    return this.appSettingsService.listStatuses();
  }

  @Put(":key")
  @Roles(UserRole.ADMIN)
  set(
    @Param("key") key: string,
    @Body() dto: SetApiKeyDto,
    @Req() req: Request & { user?: { userId?: string } }
  ) {
    return this.appSettingsService.setKey(key, dto.value, req.user?.userId);
  }

  @Delete(":key")
  @Roles(UserRole.ADMIN)
  clear(@Param("key") key: string) {
    return this.appSettingsService.clearKey(key);
  }

  @Post(":key/test")
  @Roles(UserRole.ADMIN)
  test(@Param("key") key: string, @Body() dto: TestApiKeyDto) {
    return this.appSettingsService.testKey(key, dto?.value);
  }
}
