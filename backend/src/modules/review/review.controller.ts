import { Body, Controller, Get, Param, Patch, Post, Req, UseGuards } from "@nestjs/common";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { ReviewService } from "./review.service";
import { UpdateMetadataDto } from "./dto/update-metadata.dto";
import { ReviewerApproveDto } from "./dto/reviewer-approve.dto";
import { AdminApproveDto } from "./dto/admin-approve.dto";
import { RejectDto } from "./dto/reject.dto";

@Controller("review")
@UseGuards(RolesGuard)
export class ReviewController {
  constructor(private readonly reviewService: ReviewService) {}

  @Get("pending")
  @Roles(UserRole.REVIEWER, UserRole.ADMIN)
  async pending(@Req() req: Request & { user?: any }) {
    // This function returns documents pending reviewer/admin action.
    return this.reviewService.getPendingDocuments(req.user?.role);
  }

  @Get(":documentId/state")
  @Roles(UserRole.REVIEWER, UserRole.ADMIN)
  async state(@Param("documentId") documentId: string) {
    // This function returns the current state for review action controls.
    return this.reviewService.getReviewState(documentId);
  }

  @Patch(":documentId/metadata")
  @Roles(UserRole.REVIEWER, UserRole.ADMIN)
  async updateMetadata(@Param("documentId") documentId: string, @Body() dto: UpdateMetadataDto) {
    // This function updates extracted metadata before approval.
    return this.reviewService.updateMetadata(documentId, dto);
  }

  @Post(":documentId/reviewer-approve")
  @Roles(UserRole.REVIEWER, UserRole.ADMIN)
  async reviewerApprove(
    @Param("documentId") documentId: string,
    @Body() dto: ReviewerApproveDto,
    @Req() req: Request & { user?: any }
  ) {
    // This function stores reviewer approval details.
    return this.reviewService.reviewerApprove(documentId, req.user?.userId, dto.comment);
  }

  @Post(":documentId/admin-approve")
  @Roles(UserRole.ADMIN)
  async adminApprove(
    @Param("documentId") documentId: string,
    @Body() dto: AdminApproveDto,
    @Req() req: Request & { user?: any }
  ) {
    // This function finalizes certification after reviewer approval.
    return this.reviewService.adminApprove(documentId, req.user?.userId, dto.comment);
  }

  @Post(":documentId/reject")
  @Roles(UserRole.REVIEWER, UserRole.ADMIN)
  async reject(
    @Param("documentId") documentId: string,
    @Body() dto: RejectDto,
    @Req() req: Request & { user?: any }
  ) {
    // This function rejects the document and archives it.
    return this.reviewService.reject(documentId, req.user?.userId, dto.reason);
  }
}
