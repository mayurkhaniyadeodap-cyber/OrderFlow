export type Role = "admin" | "sales" | "printing";
export type OrderStatus = "Draft" | "Live";
export type PrintingStatus = "New" | "Processing" | "Print Done";
export type PhotoStatus = "Pending" | "Confirmed" | "Rejected";

export interface User {
  id: number;
  username: string;
  full_name: string | null;
  role: Role;
}

export interface ClientConfig {
  max_upload_mb: number;
  timezone: string;
}

export interface OrderSummary {
  id: number;
  internal_order_no: string | null;
  po_number: string | null;
  customer_name: string | null;
  status: OrderStatus;
  printing_status: PrintingStatus | null;
  live_at: string | null;
  created_at: string;
  updated_at: string;
  total: number | null;
  item_count: number;
  total_quantity: number;
  source_filename: string | null;
  is_archived: boolean;
  has_customization: boolean;
  warning_count: number;
  photo_status: PhotoStatus | null;
}

export interface Attachment {
  id: number;
  item_id?: number | null;
  filename: string;
  content_type: string;
  uploaded_by: string;
  uploaded_at: string;
  url: string;
}

export interface OrderItem {
  id: number | null;
  position?: number;
  sku: string | null;
  product_name: string | null;
  quantity: number | null;
  rate: number | null;
  original_rate: number | null;
  value: number | null;
  printing_price: number | null;
  weight: string | null;
  hsn: string | null;
  tax: string | null;
  location: string | null;
  customization_names: string[];
  customization_text: string | null;
  logo_reference: string | null;
  notes: string | null;
  attachments?: Attachment[];
  photo_status?: PhotoStatus | null;
  photo_reviewed_by?: string | null;
  photo_reviewed_at?: string | null;
  photo_review_note?: string | null;
  photos?: Attachment[];
}

export interface ExtractionWarning {
  field: string;
  level: "error" | "warning" | "info";
  message: string;
}

export interface Comment {
  id: number;
  actor: string;
  actor_role: Role | null;
  text: string;
  created_at: string;
}

export interface ActivityEvent {
  id: number;
  actor: string;
  actor_role: Role | null;
  event: string;
  details: string | null;
  created_at: string;
}

export interface OrderDetail extends OrderSummary {
  version: number;
  source_status: string | null;
  source_order_date: string | null;
  billing_address: string | null;
  shipping_name: string | null;
  shipping_address: string | null;
  contact: string | null;
  email: string | null;
  gstin: string | null;
  executive: string | null;
  executive_mobile: string | null;
  subtotal: number | null;
  packaging_charges: number | null;
  processing_charges: number | null;
  additional_charges: number | null;
  tax: number | null;
  global_customization: string | null;
  global_names: string[];
  global_logo_reference: string | null;
  global_notes: string | null;
  source_meta: Record<string, unknown>;
  extraction_note: string | null;
  extraction_warnings: ExtractionWarning[];
  created_by: string | null;
  published_by: string | null;
  processing_at: string | null;
  print_done_at: string | null;
  has_source_pdf: boolean;
  items: OrderItem[];
  global_attachments: Attachment[];
  photos: Attachment[];
  comments: Comment[];
  activity: ActivityEvent[];
  permissions: {
    can_edit: boolean;
    can_publish: boolean;
    can_comment: boolean;
    next_printing_statuses: PrintingStatus[];
    can_upload_photos: boolean;
    can_review_photos: boolean;
    can_delete: boolean;
    can_restore: boolean;
  };
}

export interface DashboardData {
  role: Role;
  counts: {
    total: number;
    draft?: number;
    live: number;
    awaiting_printing: number;
    processing: number;
    print_done: number;
  };
  recent: OrderSummary[];
}

export interface AttentionData {
  count: number;
  items: OrderSummary[];
}

/** Dashboard charts. Customer totals and the pipeline are absent for Printing; executives are Admin only. */
export interface Insights {
  role: Role;
  days: number;
  trend: { date: string; created: number; published: number; finished: number }[];
  job_ages: { label: string; count: number }[];
  top_customers?: { name: string; total: number }[];
  pipeline?: { uploaded: number; published: number; processing: number; print_done: number };
  executives?: { name: string; orders: number }[];
}

// ---------------------------------------------------------------- Admin panel
export interface AdminUser {
  id: number;
  username: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  created_at: string;
  updated_at: string | null;
  last_login_at: string | null;
}

export interface ActivityEntry {
  id: string;
  source: "order" | "admin";
  created_at: string;
  actor: string;
  actor_role: Role | null;
  action: string;
  label: string;
  details: string | null;
  order_id: number | null;
  target: string | null;
  order_customer: string | null;
  order_po: string | null;
}

export interface AdminDashboardData {
  orders: { total: number; draft: number; live: number; archived: number; new: number; processing: number; print_done: number };
  users: Record<Role, { active: number; inactive: number }>;
  trend: { date: string; created: number; published: number }[];
  oldest_open: OrderSummary[];
  recent_activity: ActivityEntry[];
}

export interface EditableSettings {
  max_upload_mb: number;
  token_expire_minutes: number;
}

export interface BackupInfo {
  name: string;
  size_bytes: number;
  created_at: string;
  upload_files?: number;
}

export interface PhotoReviewRow {
  order_id: number;
  internal_order_no: string | null;
  po_number: string | null;
  customer_name: string | null;
  executive: string | null;
  sales_user: string | null;
  printing_status: PrintingStatus | null;
  live_at: string | null;
  item_id: number;
  position: number;
  sku: string | null;
  quantity: number | null;
  photo_status: PhotoStatus | null;
  photo_count: number;
  last_photo_at: string | null;
  photo_reviewed_by: string | null;
  photo_reviewed_at: string | null;
  photo_review_note: string | null;
}

export interface SalesContactRow {
  id: number;
  name: string;
  mobile: string | null;
  source: "extracted" | "manual" | "admin" | "backfill";
  created_by: string | null;
  created_at: string;
  updated_at: string | null;
  orders: number;
}
