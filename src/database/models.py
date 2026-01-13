from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, relationship

# 1. 定义基类，所有模型都要继承它
class Base(DeclarativeBase):
    pass

# 2. 定义【审计任务主表】
# 记录一次请求的总体情况：谁查的？查的啥？最后结果是啥？
class AuditTask(Base):
    __tablename__ = "audit_tasks"

    id = Column(Integer, primary_key=True, index=True)  # 任务ID，自动生成 1, 2, 3...
    raw_data = Column(Text, nullable=False)             # 原始报关单文本
    created_at = Column(DateTime, default=datetime.now) # 创建时间
    
    # 最终结论 (pass/risk)
    final_status = Column(String(50), nullable=True)    
    # 总结摘要 (例如: "建议转人工...")
    summary = Column(Text, nullable=True)               

    # 建立与子表的关系 (方便后续查询，任务.details 就能拿到所有明细)
    details = relationship("AuditDetail", back_populates="task")

# 3. 定义【审计明细表】
# 记录该任务下，每一条规则具体的运行结果
class AuditDetail(Base):
    __tablename__ = "audit_details"

    id = Column(Integer, primary_key=True, index=True)
    
    # 外键：关联到主表的 id
    task_id = Column(Integer, ForeignKey("audit_tasks.id"))
    
    rule_id = Column(String(50))     # 规则ID (如 R01)
    rule_name = Column(String(100))  # 规则名称 (如 违禁品排查)
    is_risk = Column(Boolean)        # 是否有风险 (True/False)
    llm_reason = Column(Text)        # AI 给出的理由
    
    # 反向关联
    task = relationship("AuditTask", back_populates="details")

# 4. 定义【批量任务主表】
class BatchTask(Base):
    __tablename__ = "batch_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_uuid = Column(String(50), unique=True, index=True, nullable=False)  # 前端查询用的 UUID

    # 统计信息
    total_count = Column(Integer, default=0)      # 总记录数
    completed_count = Column(Integer, default=0)  # 已完成数
    failed_count = Column(Integer, default=0)     # 失败数

    # 状态: pending/processing/completed/failed
    status = Column(String(20), default="pending")
    error_message = Column(Text, nullable=True)   # 整体错误信息

    created_at = Column(DateTime, default=datetime.now)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

    # 关联的子表
    items = relationship("BatchItem", back_populates="batch_task", cascade="all, delete-orphan")

# 5. 定义【批量任务明细表】
class BatchItem(Base):
    __tablename__ = "batch_items"

    id = Column(Integer, primary_key=True, index=True)

    # 外键关联批量任务
    batch_task_id = Column(Integer, ForeignKey("batch_tasks.id"))

    # 原始数据
    row_index = Column(Integer)                    # Excel 中的行号
    data_type = Column(String(20))                 # text 或 image
    content = Column(Text)                         # 文本内容或图片 URL

    # 处理状态: pending/processing/completed/failed
    status = Column(String(20), default="pending")

    # 结果概要（用于快速显示）
    result_summary = Column(String(50))            # pass 或 risk
    error_message = Column(Text, nullable=True)    # 错误信息

    # 详细结果（完整分析结果，JSON 格式）
    detail_result = Column(JSON, nullable=True)

    # 反向关联
    batch_task = relationship("BatchTask", back_populates="items")