import { Injectable } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { CreateTicketDto } from "./dto/create-ticket.dto";
import { SupportTicketEntity } from "./entities/support-ticket.entity";

@Injectable()
export class SupportService {
  constructor(
    @InjectRepository(SupportTicketEntity)
    private readonly ticketRepo: Repository<SupportTicketEntity>
  ) {}

  async createTicket(dto: CreateTicketDto, userId?: string) {
    const ticket = this.ticketRepo.create({
      documentId: dto.documentId,
      sessionId: dto.sessionId,
      raisedBy: userId,
      question: dto.question,
      answerSnapshot: dto.answerSnapshot,
      note: dto.note,
      status: "open"
    });
    await this.ticketRepo.save(ticket);
    return { ticketId: ticket.id, status: "open" };
  }
}
