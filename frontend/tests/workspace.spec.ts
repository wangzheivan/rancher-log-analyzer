import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const archive = process.env.FIXTURE_ARCHIVE || "/tmp/rancher-scale.tar.gz";
test("大规模分页、Pod日志、详情返回、事件、分类和原文安全", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const requests: string[] = [];
  page.on("request", (r) => requests.push(r.url()));
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Browser acceptance" },
    })
  ).json();
  try {
    await page.goto("/#case=" + c.id);
    await page.getByLabel("上传采集包文件").setInputFiles(archive);
    await expect(page.locator(".stat-value").nth(1)).toContainText("10000", {
      timeout: 60000,
    });
    expect(requests.some((u) => u.includes("/summary"))).toBe(false);
    expect(requests.some((u) => /\/files\//.test(u))).toBe(false);
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "Pod 工作负载", exact: true })
      .click();
    await expect(page.locator("tbody tr")).toHaveCount(50);
    await page.getByLabel("搜索 Pod", { exact: true }).fill("app-00000");
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: "app-00000", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Pod 详情", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("example/web:1", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("synthetic retry", { exact: false }),
    ).toBeVisible();
    await page.getByRole("button", { name: "← 返回并恢复列表" }).click();
    await expect(page.getByLabel("搜索 Pod", { exact: true })).toHaveValue(
      "app-00000",
    );
    await expect(page.locator("tbody tr")).toHaveCount(1);
    await page.getByRole("button", { name: "查看日志 · 3" }).click();
    await expect(
      page.getByRole("combobox", { name: "命名空间", exact: true }),
    ).toHaveValue("ns-000");
    await expect(page.getByLabel("文件内容")).toContainText("ONLY-AT-END");
    await expect(page.locator(".log-line")).toHaveCount(250);
    await page.screenshot({
      path: "../artifacts/pod-logs.png",
      fullPage: true,
    });
    await page.getByRole("button", { name: "向前读取", exact: true }).click();
    await expect(page.getByLabel("文件内容")).toContainText("line 101");
    await page.getByRole("button", { name: "开头", exact: true }).click();
    await expect(page.getByLabel("文件内容")).toContainText(
      "<script>window.pwned=1</script>",
    );
    expect(await page.evaluate(() => "pwned" in window)).toBe(false);
    await page.getByLabel("日志关键字").fill("only-at-end");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.locator(".log-line")).toHaveCount(1);
    await page.getByLabel("日志关键字").fill("not-found");
    await page.getByRole("button", { name: "搜索", exact: true }).click();
    await expect(page.getByLabel("文件内容")).toContainText("未找到匹配");
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "Pod 日志", exact: true })
      .click();
    await page
      .getByRole("combobox", { name: "Pod", exact: true })
      .fill("app-00000");
    await page.getByRole("option").filter({ hasText: "app-00000" }).click();
    await expect(page.getByLabel("文件内容")).toContainText("ONLY-AT-END");
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "组件日志", exact: true })
      .click();
    await expect(page.getByLabel("文件内容")).toContainText(
      "synthetic kubelet",
    );
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "采集完整性", exact: true })
      .click();
    await expect(
      page.getByText("10000", { exact: false }).first(),
    ).toBeVisible();
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "集群节点", exact: true })
      .click();
    await expect(page.locator("tbody tr")).toHaveCount(50);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "node-050", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "node-050", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Node 详情", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "← 返回并恢复列表" }).click();
    await expect(
      page.getByRole("button", { name: "node-050", exact: true }),
    ).toBeVisible();
    await page.screenshot({
      path: "../artifacts/workspace.png",
      fullPage: true,
    });
    const original = await page.getByLabel("选择采集包").inputValue();
    await page
      .getByLabel("上传采集包文件")
      .setInputFiles("/tmp/rancher-ui-fixture.tar.gz");
    await expect(page.getByLabel("选择采集包").locator("option")).toHaveCount(
      3,
    );
    const second = await page
      .getByLabel("选择采集包")
      .locator("option")
      .last()
      .getAttribute("value");
    await page.getByLabel("选择采集包").selectOption(second!);
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "采集概览", exact: true })
      .click();
    await expect(page.locator(".summary-banner")).toContainText("fixture-node");
    await page.getByLabel("选择采集包").selectOption(original);
    await expect(page.locator(".stat-value").nth(1)).toContainText("10000");
    expect(errors).toEqual([]);
  } finally {
    await request.delete("/api/v1/cases/" + c.id);
  }
});
