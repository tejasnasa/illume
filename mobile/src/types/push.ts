/**
 * Push notification registration shapes.
 *
 * @module PushTypes
 */

/**
 * Whether the signed-in user has any device registered for push.
 *
 * The count is there so the client can tell "registered on this device"
 * from "registered somewhere else", which is the difference between
 * asking for permission and not.
 */
export default interface PushTokenStatus {
  /** Whether the user has at least one registered device. */
  registered: boolean;
  /** How many devices are registered. */
  token_count: number;
}
