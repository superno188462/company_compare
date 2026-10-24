/** COL-FE-DATA-02：折叠浏览组件的类型及声明；本阶段不实现或渲染新组件。 */
import type { ReactElement } from "react";
import type { ErrorInfo } from "../contracts/boundary.js";
import type {
  CollectedRecord, CollectionOverview, CollectionRecordsPage, CollectionToolView, Evidence,
} from "../contracts/generated.js";

export interface CollectionBrowserProps {
  /** 浏览概览；初读未完成时null。 */
  overview: CollectionOverview | null;
  /** 当前会话写任务互斥状态。 */
  busy: boolean;
  /** 安全读取错误；null表示无。 */
  error: ErrorInfo | null;
  /** 只允许当前payload的user_self/user_other证据，不重复添加API材料。 */
  manualEvidence: Evidence[];
  /** 重新读取存量概览，不主动更新上游。 */
  onReload(): void;
}

export interface CollectionToolPanelProps {
  tool: CollectionToolView;
  /** 当前本地展示页，未读取时null。 */
  records: CollectionRecordsPage | null;
  readState: "idle" | "loading" | "ready" | "error";
  readError: ErrorInfo | null;
  busy: boolean;
  /** 只读本地材料page，不是上游页。 */
  onReadPage(page: number): void;
  /** 显式继续取所选工具的下一上游页。 */
  onLoadMore(): void;
  /** 显式更新此工具，新批次不修改原报告。 */
  onRefresh(): void;
}

export interface CollectedRecordCardProps {
  record: CollectedRecord;
  /** 已知是否在报告中；旧结果无法映射时null，不根据内容相似猜测。 */
  reportIncluded: boolean | null;
}

/** 仅声明组件边界，类型评审和契约测试评审完成后才填业务实现。 */
export declare function CollectionBrowser(props: CollectionBrowserProps): ReactElement;
export declare function CollectionToolPanel(props: CollectionToolPanelProps): ReactElement;
export declare function CollectedRecordCard(props: CollectedRecordCardProps): ReactElement;
