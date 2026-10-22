import { test, expect } from "@playwright/test";
test("已部署复现包：嵌套日志关联与页面阅读", async ({ page, request }) => {
  test.skip(
    !process.env.EXISTING_WORKSPACE,
    "Only run explicitly against a restored private workspace",
  );
  const cases = await (await request.get("/api/v1/cases")).json();
  const c = cases.find((item: any) =>
    item.bundles.some((b: any) => b.state === "ready"),
  );
  expect(c).toBeTruthy();
  const b = c.bundles.find((item: any) => item.state === "ready");
  const base = "/api/v1/bundles/" + b.id;
  const logs = await (
    await request.get(base + "/catalog/logs?limit=200")
  ).json();
  const nested = logs.items.filter((l: any) => l.variant === "instance");
  expect(nested.length).toBe(Number(process.env.EXPECTED_NESTED_LOGS || 8));
  expect(nested.every((l: any) => l.snapshotPodId)).toBe(true);
  const chosen = nested.find((l: any) => l.status === "ok");
  await page.goto(
    "/#" +
      new URLSearchParams({
        case: c.id,
        bundle: b.id,
        page: "pods",
        q: chosen.name,
      }),
  );
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page.getByRole("button", { name: /查看日志 ·/ }).click();
  await expect(page.getByLabel("文件内容")).not.toContainText("正在读取…");
  await expect(page.locator(".log-line").first()).toBeVisible();
  await expect(
    page.getByRole("combobox", { name: "命名空间", exact: true }),
  ).toHaveValue(chosen.namespace);
  const raw = await page.locator(".log-line").first().innerText();
  expect(raw.length).toBeGreaterThan(1);
  await page
    .getByLabel("日志关键字")
    .fill("unlikely-search-keyword-for-acceptance-12345");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByLabel("文件内容")).toContainText("未找到匹配");
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "组件与系统日志", exact: true })
    .click();
  await expect(page.locator(".log-source").first()).toBeVisible();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "采集完整性", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "采集完整性", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "../artifacts/reproduction-private.png",
    fullPage: true,
  });
});
