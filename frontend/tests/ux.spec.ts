import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";
const archive = process.env.UX_ARCHIVE || "/tmp/rancher-scale.tar.gz";
test("卡片、资源快照、分类目录与全部页面控件", async ({ page, request }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "新建案例", exact: true }).click();
  await page.getByLabel("案例名称", { exact: true }).fill("UX acceptance");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await expect(
    page.getByLabel("选择案例").locator("option:checked"),
  ).toHaveText("UX acceptance");
  const caseId = await page.getByLabel("选择案例").inputValue();
  try {
    await page.getByLabel("上传采集包文件").setInputFiles(archive);
    await expect(page.locator(".summary-banner")).toBeVisible({
      timeout: 60000,
    });
    await expect(
      page.getByRole("heading", { name: /案例内采集包/ }),
    ).toBeVisible();
    await expect(page.locator(".bundle-row")).toHaveCount(1);
    const bundleId = await page.getByLabel("选择采集包").inputValue();
    const base = "/api/v1/bundles/" + bundleId;
    const overview = await (await request.get(base + "/overview")).json();
    if (process.env.UX_ARCHIVE) {
      expect(overview.counts).toMatchObject({
        files: 324,
        pods: 76,
        nodes: 3,
        namespaces: 14,
      });
      const logs = await (
        await request.get(base + "/catalog/logs?limit=200")
      ).json();
      expect(
        logs.items.filter((l: any) => l.path.includes("/podlogs/")),
      ).toHaveLength(112);
    }
    const node = (
      await (await request.get(base + "/catalog/nodes?limit=1")).json()
    ).items[0];
    const nav = (name: string) =>
      page
        .getByRole("navigation")
        .getByRole("button", { name, exact: true })
        .click();
    await nav("集群节点");
    await expect(page.locator(".node-grid>.panel")).toHaveCount(
      Math.min(12, overview.counts.nodes),
    );
    await page.getByLabel("搜索节点", { exact: true }).fill(node.ip);
    const ipMatches = (
      await (
        await request.get(
          base + "/catalog/nodes?q=" + encodeURIComponent(node.ip),
        )
      ).json()
    ).total;
    await expect(page.locator(".node-grid>.panel")).toHaveCount(
      Math.min(12, ipMatches),
    );
    await expect(
      page.getByRole("button", { name: node.name, exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: node.name, exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Node 详情", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "← 返回并恢复列表" }).click();
    await expect(page.getByLabel("搜索节点")).toHaveValue(node.ip);
    await expect(
      page
        .getByRole("navigation")
        .getByRole("button", { name: "事件浏览", exact: true }),
    ).toHaveCount(0);
    await page.goto(
      "/#" +
        new URLSearchParams({ case: caseId, bundle: bundleId, page: "events" }),
    );
    await expect(
      page.getByRole("heading", { name: "资源快照", exact: true }),
    ).toBeVisible();
    await expect(page).toHaveURL(/resource=events/);
    await nav("资源快照");
    await expect(page.locator(".resource-menu")).toBeVisible();
    await page.getByLabel("搜索资源类型").fill("pods");
    await page
      .locator(".resource-menu>button")
      .filter({ hasText: /^pods/ })
      .click();
    await expect(page.locator(".resource-content th").first()).toBeVisible();
    expect(
      await page.locator(".resource-content th").allTextContents(),
    ).not.toContain("id");
    await nav("原始文件");
    await expect(page.getByLabel("文件用途分类")).toBeVisible();
    await page
      .getByLabel("文件用途分类")
      .getByRole("button", { name: /^Pod 日志/ })
      .click();
    await expect(page.locator("tbody tr").first()).toContainText("/podlogs/");
    await page
      .locator(".directory-menu>button")
      .filter({ hasText: "rke2" })
      .click();
    await expect(page.locator(".directory-breadcrumb")).toContainText("rke2");
    await page.getByLabel("搜索文件").fill("0.log");
    await expect(page.getByLabel("搜索文件")).toHaveValue("0.log");
    await nav("Pod 日志");
    await page.getByRole("combobox", { name: "命名空间", exact: true }).focus();
    const options = page.getByRole("listbox", { name: "命名空间候选项" });
    await expect(options).toBeVisible();
    await expect(options.locator(".async-page")).toContainText(
      "共 " + overview.counts.namespaces + " 项",
    );
    await page
      .getByRole("combobox", { name: "命名空间", exact: true })
      .fill(process.env.UX_ARCHIVE ? "kube-system" : "ns-099");
    if (process.env.UX_ARCHIVE)
      await expect(
        page.getByRole("option", { name: /^kube-system/ }),
      ).toBeVisible();
    else
      await expect(page.getByRole("option", { name: /^ns-099/ })).toBeVisible();
    await page.keyboard.press("Tab");
    for (const width of [1440, 1280, 1024, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      for (const name of [
        "采集概览",
        "集群节点",
        "Pod 工作负载",
        "Pod 日志",
        "组件日志",
        "资源快照",
        "主机与 etcd",
        "采集完整性",
        "原始文件",
      ]) {
        await nav(name);
        await page.waitForTimeout(70);
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          name + " @" + width,
        ).toBe(true);
        const bad = await page
          .locator(
            ".search-field,.async-control,select,input:not([type=file]):not([type=checkbox]):not([type=radio])",
          )
          .evaluateAll((elements) =>
            elements
              .filter((el) => {
                const r = el.getBoundingClientRect();
                return (
                  r.width > 0 &&
                  r.height > 0 &&
                  !el.closest(".search-field input,.async-control input") &&
                  Math.abs(r.height - 40) > 1
                );
              })
              .map((el) => ({
                tag: el.tagName,
                class: el.className,
                height: el.getBoundingClientRect().height,
              })),
          );
        expect(bad, name + " controls @" + width).toEqual([]);
        expect(
          await page.locator(".search-field").evaluateAll((elements) =>
            elements.every((el) => {
              const svg = el.querySelector("svg"),
                input = el.querySelector("input");
              return (
                !svg ||
                !input ||
                svg.getBoundingClientRect().right <=
                  input.getBoundingClientRect().left
              );
            }),
          ),
        ).toBe(true);
      }
    }
    await nav("Pod 日志");
    await page.getByRole("combobox", { name: "命名空间", exact: true }).focus();
    const popup = await page
      .getByRole("listbox", { name: "命名空间候选项" })
      .boundingBox();
    expect(popup!.x + popup!.width).toBeLessThanOrEqual(391);
    await page
      .getByRole("combobox", { name: "命名空间", exact: true })
      .fill("");
    await page.keyboard.press("Tab");
    await nav("原始文件");
    await page.getByLabel("搜索文件").fill("summary.txt");
    await page
      .getByRole("button", { name: "summary.txt", exact: true })
      .click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByLabel("文件内容")).not.toContainText("正在读取…");
    expect(
      await page
        .locator("dialog .search-field")
        .evaluate((el) => el.getBoundingClientRect().height),
    ).toBe(40);
    await page.getByRole("button", { name: "关闭文件" }).click();
    await page.setViewportSize({ width: 1440, height: 1000 });
    await nav("集群节点");
    await page.screenshot({
      path: "../artifacts/ux-nodes.png",
      fullPage: true,
    });
    await nav("原始文件");
    await page.screenshot({
      path: "../artifacts/ux-files.png",
      fullPage: true,
    });
    await nav("采集概览");
    await page.screenshot({
      path: "../artifacts/ux-overview.png",
      fullPage: true,
    });
    expect(errors).toEqual([]);
  } finally {
    await request.delete("/api/v1/cases/" + caseId);
  }
});

test("案例内采集包分页、切换与删除", async ({ page, request }) => {
  const c = await (
    await request.post("/api/v1/cases", {
      data: { name: "Bundle management acceptance" },
    })
  ).json();
  try {
    for (let i = 0; i < 11; i++)
      expect(
        (
          await request.post(
            `/api/v1/cases/${c.id}/bundles?filename=fixture-${i}.tgz`,
            {
              data: readFileSync("/tmp/rancher-ui-fixture.tar.gz"),
              headers: { "Content-Type": "application/gzip" },
            },
          )
        ).status(),
      ).toBe(202);
    await expect
      .poll(async () => {
        const cases = await (await request.get("/api/v1/cases")).json();
        return cases
          .find((item: any) => item.id === c.id)
          .bundles.every((b: any) => b.state === "ready");
      })
      .toBe(true);
    await page.goto(
      "/#" + new URLSearchParams({ case: c.id, page: "overview" }),
    );
    await expect(page.locator(".bundle-row")).toHaveCount(10);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    await expect(page.locator(".bundle-row")).toHaveCount(1);
    await page.locator(".bundle-name").click();
    await expect(page.locator(".bundle-row.selected")).toHaveCount(1);
    page.on("dialog", (d) => d.accept());
    await page
      .locator(".bundle-row")
      .getByRole("button", { name: "删除", exact: true })
      .click();
    await expect(page.locator(".bundle-row")).toHaveCount(10);
    await expect(
      page.getByRole("heading", { name: /案例内采集包 · 10/ }),
    ).toBeVisible();
  } finally {
    await request.delete("/api/v1/cases/" + c.id);
  }
});
