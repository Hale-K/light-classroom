/** rbac 领域 API（由 api/index.ts 拆分）。 */
import type {
  MenuPermissionBinding,
  PermissionGroup,
  RoleMenuPreview,
  RoleInfo,
  RoleMembersResult,
} from '@/types'
import { http, unwrap } from './http'

export const rbacApi = {
  /** 权限点目录（按模块分组） */
  permissions: () => unwrap<PermissionGroup[]>(http.get('/rbac/permissions')),
  /** 角色列表 */
  roles: () => unwrap<RoleInfo[]>(http.get('/rbac/roles')),
  /** 新建角色 */
  createRole: (data: { code: string; name: string; description?: string }) =>
    unwrap<{ id: number; code: string; name: string }>(http.post('/rbac/roles', data)),
  /** 编辑角色（名称/说明） */
  updateRole: (id: number, data: { name: string; description?: string }) =>
    unwrap<{ id: number; name: string; description: string }>(
      http.patch(`/rbac/roles/${id}`, data),
    ),
  /** 删除角色 */
  deleteRole: (id: number) => unwrap<null>(http.delete(`/rbac/roles/${id}`)),
  /** 角色已拥有的权限点编码 */
  rolePermissions: (roleId: number) =>
    unwrap<string[]>(http.get(`/rbac/roles/${roleId}/permissions`)),
  /** 整量设置角色的权限点 */
  setRolePermissions: (roleId: number, permissions: string[]) =>
    unwrap<string[]>(http.put(`/rbac/roles/${roleId}/permissions`, { permissions })),
  /** 角色成员候选及当前分配状态 */
  roleMembers: (roleId: number) =>
    unwrap<RoleMembersResult>(http.get(`/rbac/roles/${roleId}/members`)),
  /** 整量设置角色成员，不影响这些人员的其他角色 */
  setRoleMembers: (roleId: number, userIds: number[]) =>
    unwrap<number[]>(http.put(`/rbac/roles/${roleId}/members`, { user_ids: userIds })),
  /** 按权限码预览角色侧栏菜单（可传草稿勾选） */
  roleMenuPreview: (roleId: number, codes?: string[]) =>
    unwrap<RoleMenuPreview>(
      http.get(`/rbac/roles/${roleId}/menu-preview`, {
        params: codes ? { codes: codes.join(',') } : undefined,
      }),
    ),
  /** 菜单可见权限映射列表 */
  menuPermissions: () =>
    unwrap<MenuPermissionBinding[]>(http.get('/rbac/menu-permissions')),
  /** 整量设置某菜单的可见权限点 */
  setMenuPermissions: (menuKey: string, permissions: string[]) =>
    unwrap<{ menu_key: string; permissions: string[] }>(
      http.put(`/rbac/menu-permissions/${menuKey}`, { permissions }),
    ),
}

