import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const archive = process.env.SAMPLE_ARCHIVE || "/tmp/rancher-sample.tar.gz";
const fixture = process.env.FIXTURE_ARCHIVE || "/tmp/rancher-ui-fixture.tar.gz";

test("真实采集包：案例、多包切换、资源浏览、原文搜索与清理", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const fileRequests: string[] = [];
  page.on("request", (r) => {
    if (/\/files\//.test(r.url())) fileRequests.push(r.url());
  });
  await page.goto("/");
  await page.getByRole("button", { name: "新建案例", exact: true }).click();
  await page.getByLabel("案例名称", { exact: true }).fill("WSL 真实样本验收");
  await page.getByRole("button", { name: "保存案例", exact: true }).click();
  await expect(page.getByLabel("当前案例")).toContainText("WSL 真实样本验收");
  await page.getByLabel("上传采集包文件").setInputFiles(archive);
  await expect(page.locator("#content")).toBeVisible();
  await expect(page.locator(".stat-value").first()).toContainText("3");
  await expect(page.locator(".stat-value").nth(1)).toContainText("51");
  await expect(page.locator(".stat-value").nth(3)).toContainText("284");
  expect(fileRequests).toHaveLength(0);
  await page.screenshot({ path: "../artifacts/overview.png", fullPage: true });
  await page.locator('nav button[data-page="nodes"]').click();
  await expect(page.locator(".node-grid .panel")).toHaveCount(3);
  await expect(page.locator(".node-grid")).toContainText(
    "MemoryPressure: False",
  );
  await page.locator('nav button[data-page="pods"]').click();
  await page.getByLabel("命名空间筛选").selectOption("cattle-system");
  await expect(page.locator("tbody tr")).toHaveCount(4);
  await page
    .locator("tbody tr")
    .first()
    .getByRole("button", { name: "当前", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByLabel("日志关键字").fill("error");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByLabel("文件内容")).not.toContainText("正在读取…");
  await page.getByRole("button", { name: "关闭文件" }).click();
  await page.locator('nav button[data-page="resources"]').click();
  await page.getByRole("button", { name: /^events\s*0$/ }).click();
  await expect(page.getByText("采集时未发现该类资源")).toBeVisible();
  await page.locator('nav button[data-page="system"]').click();
  await expect(page.locator("#content")).toContainText("Mem:");
  await page.locator('nav button[data-page="files"]').click();
  await page.getByLabel("搜索文件").fill("systeminfo/freeh");
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await page
    .getByRole("button", { name: "systeminfo/freeh", exact: true })
    .click();
  await expect(page.getByLabel("文件内容")).toContainText("Mem:");
  await page.getByRole("button", { name: "关闭文件" }).click();
  await page.getByRole("button", { name: "重命名案例", exact: true }).click();
  await page.getByLabel("案例名称", { exact: true }).fill("已验收案例");
  await page.getByRole("button", { name: "保存案例", exact: true }).click();
  await page.getByLabel("上传采集包文件").setInputFiles(fixture);
  await expect(page.locator("#bundle-select option")).toHaveCount(3);
  const options = await page
    .locator("#bundle-select option")
    .evaluateAll((els) => els.map((e) => (e as HTMLOptionElement).value));
  await page.getByLabel(/采集包 ·/).selectOption(options[2]);
  await page.locator('nav button[data-page="overview"]').click();
  await expect(page.locator(".summary-banner")).toContainText("fixture-node");
  await page.getByLabel(/采集包 ·/).selectOption(options[1]);
  await expect(page.locator(".summary-banner")).toContainText("node22");
  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "删除案例", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "让采集信息，变得一目了然" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("日志分页、无匹配与 HTML 转义，移动端可浏览", async ({
  page,
  request,
}) => {
  const c = await (
    await request.post("/api/v1/cases", { data: { name: "日志边界验收" } })
  ).json();
  const r = await request.post(
    `/api/v1/cases/${c.id}/bundles?filename=fixture.tgz`,
    {
      data: readFileSync(fixture),
      headers: { "Content-Type": "application/gzip" },
    },
  );
  expect(r.status()).toBe(202);
  await page.goto("/");
  await expect(page.locator("#content")).toBeVisible();
  await page.locator('nav button[data-page="files"]').click();
  await page.getByLabel("搜索文件").fill("test.log");
  await page.getByRole("button", { name: "test.log", exact: true }).click();
  await expect(page.getByLabel("文件内容")).toContainText(
    "<script>window.pwned=1</script>",
  );
  expect(await page.evaluate(() => "pwned" in window)).toBe(false);
  await expect(page.locator(".log-line")).toHaveCount(250);
  await page.getByRole("button", { name: "继续读取" }).click();
  await expect(page.getByLabel("文件内容")).toContainText("line 250");
  await page.getByLabel("日志关键字").fill("ONLY-AT-END");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByLabel("文件内容")).toContainText("ONLY-AT-END");
  await page.getByLabel("日志关键字").fill("not-present-at-all");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await expect(page.getByLabel("文件内容")).toContainText("未找到匹配");
  await page.getByRole("button", { name: "关闭文件" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('nav button[data-page="overview"]').click();
  await expect(page.locator(".summary-banner")).toContainText("fixture-node");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByText("Pod 状态未知", {exact: true})).toBeVisible();
  await page.screenshot({ path: "../artifacts/mobile.png", fullPage: true });
  await request.delete(`/api/v1/cases/${c.id}`);
});
