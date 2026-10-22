/** FE-DATA-02：后续组件实现必须满足既有 Props；此处只绑定 React 类型。 */
import type { ComponentType } from "react";
import type {
  CandidateListProps, CoveragePanelProps, EvidenceCardProps, ManualEvidenceFormProps,
  OfficialLinksProps, ReportPanelProps, SearchPanelProps, ShareReceiptListProps,
  SubjectHeaderProps,
} from "./props.js";

/** 工作台组件骨架的 React 类型清单，不提供未实现组件的伪逻辑。 */
export interface WorkspaceComponents {
  SearchPanel: ComponentType<SearchPanelProps>;
  CandidateList: ComponentType<CandidateListProps>;
  SubjectHeader: ComponentType<SubjectHeaderProps>;
  CoveragePanel: ComponentType<CoveragePanelProps>;
  EvidenceCard: ComponentType<EvidenceCardProps>;
  ReportPanel: ComponentType<ReportPanelProps>;
  ManualEvidenceForm: ComponentType<ManualEvidenceFormProps>;
  OfficialLinks: ComponentType<OfficialLinksProps>;
  ShareReceiptList: ComponentType<ShareReceiptListProps>;
}
