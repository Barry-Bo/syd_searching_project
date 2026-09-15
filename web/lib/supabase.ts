import { createClient } from "@supabase/supabase-js";

// 只用 anon key。它是公开的，前端本来就会带上；真正的保护是数据库里的 RLS：
// 展示数据（restaurants/extractions/claims/dishes）匿名只读，
// 行为数据（search_logs/feedback）匿名只写不读。
// service_role 永远不进这个项目——它绕过 RLS，泄漏等于整库敞开。
export const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);
