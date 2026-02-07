import Learn from "./Learn";
import type { UnifiedRole } from "../api/unified";

export default function TeachAI(_props: { initialRole?: UnifiedRole; lockRole?: boolean }) {
  return <Learn />;
}
