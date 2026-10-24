/** 固定官方入口只供人浏览，应用不读取目标网页。 */
import dictionary from "../../../contracts/text-dict.json";

export function OfficialRecovery({ toolName, onSupplement }: { toolName: string | null; onSupplement(): void }) {
  const copy = dictionary.collection_labels;
  const site = dictionary.official_sites.find((item) => item.site_id === (
    toolName === "get_chattel_mortgage_info" ? "zhongdengwang" :
    toolName !== null && ["get_dishonest_info", "get_judgment_debtor_info", "get_high_consumption_restriction"].includes(toolName) ? "zxgk" : "gsxt"));
  return <div className="official-recovery">
    {toolName === "get_land_mortgage_info" ? <p>{copy.land_note}</p> : site && <>
      <a href={site.url} target="_blank" rel="noopener noreferrer">{copy.open_official}：{site.label} ↗</a>
      <button type="button" className="secondary-button" onClick={() => { void navigator.clipboard.writeText(site.url).catch(() => window.prompt(dictionary.labels.official_copy_fallback, site.url)); }}>{copy.copy_official}</button>
    </>}
    <button type="button" className="secondary-button" onClick={onSupplement}>{copy.supplement}</button>
  </div>;
}
