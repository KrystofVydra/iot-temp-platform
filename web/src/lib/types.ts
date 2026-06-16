export type User = {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
};

// ===========================================================================
// User-facing controller types
// ===========================================================================

export type GatewayBrief = {
  id: number;
  device_key: string;
  name: string;
  location?: string | null;
};

export type ControllerLatest = {
  time: string | null;
  temperature_avg: number | null;
  battery_v: number | null;
  door_open: boolean | null;
  any_node_error: boolean;
};

export type Controller = {
  id: number;
  sn: string;
  name: string;
  location: string | null;
  gateway: GatewayBrief;
  node_count: number;
  last_seen_at: string | null;
  latest: ControllerLatest;
};

export type NodeLatest = {
  time: string | null;
  temperature: number | null;
  lux: number | null;
  err: string | null;
};

export type NodeOut = {
  id: number;
  node_index: number;
  name: string | null;
  has_lux: boolean;
  last_seen_at: string | null;
  latest: NodeLatest;
};

export type LatestTelemetry = {
  time: string | null;
  battery_v: number | null;
  door_open: boolean | null;
};

export type ControllerDetail = {
  id: number;
  sn: string;
  name: string;
  location: string | null;
  gateway: GatewayBrief;
  nodes: NodeOut[];
  latest_telemetry: LatestTelemetry;
};

export type ReadingPoint = {
  time: string;
  temperature_avg: number | null;
};

export type TelemetryPoint = {
  time: string;
  battery_v: number | null;
  door_open: boolean | null;
};

export type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d';

// ===========================================================================
// Admin types
// ===========================================================================

export type UserAdmin = {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  has_password: boolean;
  gateway_count: number;
};

export type GatewayForUser = {
  id: number;
  device_key: string;
  name: string;
  location: string | null;
  created_at: string;
  last_seen_at: string | null;
  mqtt_provisioned: boolean;
  controller_count: number;
};

export type UserAdminDetail = UserAdmin & {
  gateways: GatewayForUser[];
};

export type Owner = {
  id: number;
  email: string;
  display_name: string;
};

export type GatewayAdmin = {
  id: number;
  device_key: string;
  name: string;
  location: string | null;
  created_at: string;
  last_seen_at: string | null;
  mqtt_provisioned: boolean;
  owner: Owner;
  controller_count: number;
};

export type ControllerForGateway = {
  id: number;
  sn: string;
  name: string;
  location: string | null;
  created_at: string;
  last_seen_at: string | null;
  node_count: number;
};

export type PendingController = {
  id: number;
  sn: string;
  first_seen_at: string;
  last_seen_at: string;
  message_count: number;
};

export type GatewayDetailAdmin = GatewayAdmin & {
  controllers: ControllerForGateway[];
  pending_controllers: PendingController[];
};

export type CreateUserResponse = {
  user: UserAdmin;
  invitation_url: string;
};

export type ResetLinkResponse = {
  reset_url: string;
};

export type InvitationLinkResponse = {
  invitation_url: string;
};

export type CreateGatewayResponse = {
  gateway: GatewayAdmin;
  mqtt_password: string;
  ssh_command: string;
};

export type RotateMqttResponse = {
  mqtt_password: string;
  ssh_command: string;
};

export type DeviceStatus = 'online' | 'offline';

export type GatewayPatch = Partial<{
  name: string;
  location: string | null;
  user_id: number;
  mqtt_provisioned: boolean;
}>;

export type ControllerPatch = Partial<{
  name: string;
  location: string | null;
}>;

export type NodePatch = Partial<{
  name: string;
  has_lux: boolean;
}>;
