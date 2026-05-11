const charts = {};
const palette = ["#0f8b8d", "#d85c4a", "#c98212", "#3766a6", "#2e7d5b", "#7a5c99", "#4f6f52", "#b34d7d"];
const fmt = new Intl.NumberFormat("zh-CN");

function compact(value) {
  if (value === null || value === undefined) return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  if (Math.abs(number) >= 100000000) return `${(number / 100000000).toFixed(1)}亿`;
  if (Math.abs(number) >= 10000) return `${(number / 10000).toFixed(1)}万`;
  return fmt.format(Math.round(number));
}

function dateText(value) {
  if (!value) return "--";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function percentile(values, pct) {
  const nums = values.filter((v) => Number.isFinite(v)).sort((a, b) => a - b);
  if (!nums.length) return 0;
  if (nums.length === 1) return nums[0];
  const pos = (nums.length - 1) * pct;
  const low = Math.floor(pos);
  const high = Math.ceil(pos);
  return nums[low] + (nums[high] - nums[low]) * (pos - low);
}

function mean(values) {
  const nums = values.filter((v) => Number.isFinite(v));
  return nums.length ? nums.reduce((sum, v) => sum + v, 0) / nums.length : 0;
}

function stddev(values) {
  const nums = values.filter((v) => Number.isFinite(v));
  if (nums.length < 2) return 0;
  const avg = mean(nums);
  return Math.sqrt(mean(nums.map((v) => (v - avg) ** 2)));
}

function groupBy(items, key) {
  return items.reduce((acc, item) => {
    const name = item[key] || "其他";
    if (!acc[name]) acc[name] = [];
    acc[name].push(item);
    return acc;
  }, {});
}

function medianViews(items) {
  return percentile(items.map((item) => item.viewCount || 0), 0.5);
}

function drawChart(id, config) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), config);
}

function baseOptions(extra = {}) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { labels: { boxWidth: 12, color: "#18202a" } },
      tooltip: { mode: "index", intersect: false }
    },
    scales: {
      x: { grid: { color: "#eef2f6" }, ticks: { color: "#627084" } },
      y: { grid: { color: "#eef2f6" }, ticks: { color: "#627084" } }
    },
    ...extra
  };
}

function computeDerived(data) {
  const videos = data.videos || [];
  const channels = (data.channels || []).map((channel) => ({
    ...channel,
    effectiveMedianViews: Math.max(1, channel.sampleMedianViews || 0),
    effectiveSubscribers: Math.max(1, channel.subscriberCount || 0),
    viewPerSubscriber: channel.subscriberCount ? (channel.sampleMedianViews || 0) / channel.subscriberCount : 0
  }));
  const views = videos.map((video) => video.viewCount || 0);
  const avg = mean(views);
  const cv = avg ? stddev(views) / avg : 0;
  const topicGroups = groupBy(videos, "topic");
  const industryGroups = groupBy(videos, "guestIndustry");
  const topicStats = Object.entries(topicGroups)
    .map(([topic, rows]) => ({
      topic,
      count: rows.length,
      p50: percentile(rows.map((v) => v.viewCount || 0), 0.5),
      p90: percentile(rows.map((v) => v.viewCount || 0), 0.9),
      score: percentile(rows.map((v) => v.viewCount || 0), 0.5) / Math.sqrt(rows.length)
    }))
    .sort((a, b) => b.p50 - a.p50);
  const industryStats = Object.entries(industryGroups)
    .map(([industry, rows]) => ({
      industry,
      count: rows.length,
      p50: percentile(rows.map((v) => v.viewCount || 0), 0.5),
      p90: percentile(rows.map((v) => v.viewCount || 0), 0.9)
    }))
    .sort((a, b) => b.p50 - a.p50);
  return {
    channels,
    videos,
    views,
    cv,
    topicStats,
    industryStats,
    opportunityTopic: topicStats.length ? topicStats.sort((a, b) => b.score - a.score)[0].topic : "--"
  };
}

function renderMetrics(data, derived) {
  const summary = data.summary;
  setText("channelCount", compact(summary.channelCount));
  setText("videoCount", compact(summary.videoCount));
  setText("viewsP50", compact(summary.videoViewsP50));
  setText("viewsP90", compact(summary.videoViewsP90));
  setText("viewCV", derived.cv.toFixed(2));
  setText("opportunityTopic", derived.opportunityTopic);
}

function renderCoreCharts(data, derived) {
  const duration = data.summary.durationBins;
  drawChart("durationChart", {
    type: "bar",
    data: {
      labels: duration.map((d) => d.name),
      datasets: [
        { label: "视频数", data: duration.map((d) => d.count), backgroundColor: palette[0], borderRadius: 5 },
        { label: "占比 %", data: duration.map((d) => Math.round(d.share * 100)), backgroundColor: palette[2], borderRadius: 5, yAxisID: "share" }
      ]
    },
    options: baseOptions({
      scales: {
        y: { beginAtZero: true, grid: { color: "#eef2f6" } },
        share: { position: "right", beginAtZero: true, grid: { drawOnChartArea: false }, ticks: { callback: (v) => `${v}%` } },
        x: { grid: { display: false } }
      }
    })
  });

  drawChart("topicChart", {
    type: "doughnut",
    data: {
      labels: data.summary.topics.map((d) => d.name),
      datasets: [{ data: data.summary.topics.map((d) => d.count), backgroundColor: palette }]
    },
    options: baseOptions({ scales: {} })
  });

  drawChart("industryChart", {
    type: "bar",
    data: {
      labels: data.summary.guestIndustries.map((d) => d.name),
      datasets: [{ label: "视频数", data: data.summary.guestIndustries.map((d) => d.count), backgroundColor: palette[3], borderRadius: 5 }]
    },
    options: baseOptions({ indexAxis: "y" })
  });

  const validChannels = derived.channels.filter((c) => (c.sampleVideoCount || 0) > 0 && (c.sampleMedianViews || 0) > 0);
  drawChart("scatterChart", {
    type: "bubble",
    data: {
      datasets: validChannels.map((channel, index) => ({
        label: channel.title,
        data: [{ x: channel.effectiveSubscribers, y: channel.effectiveMedianViews, r: Math.max(5, Math.min(24, Math.sqrt(channel.viewCount || 1) / 900)) }],
        backgroundColor: `${palette[index % palette.length]}bb`
      }))
    },
    options: baseOptions({
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const c = validChannels[ctx.datasetIndex];
              return `${c.title}: 订阅 ${compact(c.subscriberCount)} / 中位播放 ${compact(c.sampleMedianViews)} / 样本 ${c.sampleVideoCount}`;
            }
          }
        }
      },
      scales: {
        x: { type: "logarithmic", title: { display: true, text: "订阅量（对数）" }, ticks: { callback: compact }, grid: { color: "#eef2f6" } },
        y: { type: "logarithmic", title: { display: true, text: "样本中位播放（对数）" }, ticks: { callback: compact }, grid: { color: "#eef2f6" } }
      }
    })
  });

  const efficient = validChannels.sort((a, b) => b.viewPerSubscriber - a.viewPerSubscriber).slice(0, 12);
  drawChart("efficiencyChart", {
    type: "bar",
    data: {
      labels: efficient.map((d) => d.title),
      datasets: [{ label: "中位播放 / 订阅", data: efficient.map((d) => Number(d.viewPerSubscriber.toFixed(3))), backgroundColor: palette[4], borderRadius: 5 }]
    },
    options: baseOptions({ indexAxis: "y" })
  });

  const radar = data.recommendations.radar;
  drawChart("radarChart", {
    type: "radar",
    data: {
      labels: radar.map((d) => d.axis),
      datasets: [
        { label: "市场平均", data: radar.map((d) => d.market), borderColor: palette[3], backgroundColor: "#3766a622" },
        { label: "你的频道", data: radar.map((d) => d.your_channel), borderColor: palette[0], backgroundColor: "#0f8b8d22" }
      ]
    },
    options: baseOptions({
      scales: {
        r: {
          min: 0,
          max: 100,
          ticks: { stepSize: 20, backdropColor: "transparent" },
          grid: { color: "#dfe6ee" },
          angleLines: { color: "#dfe6ee" },
          pointLabels: { color: "#18202a", font: { size: 12 } }
        }
      }
    })
  });
}

function renderResearchCharts(data, derived) {
  const bins = [
    { label: "0-1千", min: 0, max: 1000 },
    { label: "1千-5千", min: 1000, max: 5000 },
    { label: "5千-1万", min: 5000, max: 10000 },
    { label: "1万-5万", min: 10000, max: 50000 },
    { label: "5万-10万", min: 50000, max: 100000 },
    { label: "10万-50万", min: 100000, max: 500000 },
    { label: "50万以上", min: 500000, max: Infinity }
  ];
  drawChart("viewDistributionChart", {
    type: "bar",
    data: {
      labels: bins.map((b) => b.label),
      datasets: [{ label: "视频数", data: bins.map((b) => derived.views.filter((v) => v >= b.min && v < b.max).length), backgroundColor: palette[1], borderRadius: 5 }]
    },
    options: baseOptions()
  });

  const topicStats = [...derived.topicStats].sort((a, b) => b.count - a.count);
  drawChart("topicPerformanceChart", {
    type: "bar",
    data: {
      labels: topicStats.map((d) => d.topic),
      datasets: [
        { label: "P50", data: topicStats.map((d) => Math.round(d.p50)), backgroundColor: palette[0], borderRadius: 5 },
        { label: "P90", data: topicStats.map((d) => Math.round(d.p90)), backgroundColor: palette[2], borderRadius: 5 }
      ]
    },
    options: baseOptions({ scales: { y: { ticks: { callback: compact } }, x: { ticks: { maxRotation: 35, minRotation: 20 } } } })
  });

  const durationGroups = groupBy(derived.videos, "durationBin");
  const durationLabels = data.summary.durationBins.map((d) => d.name);
  drawChart("durationPerformanceChart", {
    type: "line",
    data: {
      labels: durationLabels,
      datasets: [{
        label: "中位播放",
        data: durationLabels.map((label) => Math.round(medianViews(durationGroups[label] || []))),
        borderColor: palette[3],
        backgroundColor: "#3766a622",
        tension: 0.35,
        fill: true
      }]
    },
    options: baseOptions({ scales: { y: { ticks: { callback: compact } } } })
  });

  const topEngagement = [...derived.videos]
    .filter((v) => (v.viewCount || 0) > 0)
    .map((v) => ({ ...v, likesPerK: ((v.likeCount || 0) / v.viewCount) * 1000, commentsPerK: ((v.commentCount || 0) / v.viewCount) * 1000 }))
    .sort((a, b) => b.likesPerK + b.commentsPerK - (a.likesPerK + a.commentsPerK))
    .slice(0, 12);
  drawChart("engagementChart", {
    type: "bar",
    data: {
      labels: topEngagement.map((v) => v.title.slice(0, 18)),
      datasets: [
        { label: "每千播放点赞", data: topEngagement.map((v) => Number(v.likesPerK.toFixed(1))), backgroundColor: palette[4], borderRadius: 5 },
        { label: "每千播放评论", data: topEngagement.map((v) => Number(v.commentsPerK.toFixed(1))), backgroundColor: palette[1], borderRadius: 5 }
      ]
    },
    options: baseOptions({ scales: { x: { ticks: { maxRotation: 55, minRotation: 35 } } } })
  });

  const monthGroups = {};
  derived.videos.forEach((video) => {
    const key = (video.publishedAt || "").slice(0, 7) || "未知";
    if (!monthGroups[key]) monthGroups[key] = [];
    monthGroups[key].push(video);
  });
  const months = Object.keys(monthGroups).sort().slice(-18);
  drawChart("publishTimelineChart", {
    type: "line",
    data: {
      labels: months,
      datasets: [
        { label: "发布数量", data: months.map((m) => monthGroups[m].length), borderColor: palette[0], backgroundColor: "#0f8b8d22", tension: 0.35, yAxisID: "count" },
        { label: "中位播放", data: months.map((m) => Math.round(medianViews(monthGroups[m]))), borderColor: palette[2], backgroundColor: "#c9821222", tension: 0.35, yAxisID: "views" }
      ]
    },
    options: baseOptions({
      scales: {
        count: { beginAtZero: true, title: { display: true, text: "视频数" }, grid: { color: "#eef2f6" } },
        views: { position: "right", title: { display: true, text: "中位播放" }, grid: { drawOnChartArea: false }, ticks: { callback: compact } },
        x: { ticks: { maxRotation: 35, minRotation: 20 } }
      }
    })
  });

  drawChart("opportunityChart", {
    type: "bubble",
    data: {
      datasets: topicStats.map((row, index) => ({
        label: row.topic,
        data: [{ x: row.count, y: Math.max(1, row.p50), r: Math.max(6, Math.min(24, Math.sqrt(row.p90 || 1) / 28)) }],
        backgroundColor: `${palette[index % palette.length]}bb`
      }))
    },
    options: baseOptions({
      plugins: {
        legend: { position: "bottom" },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const row = topicStats[ctx.datasetIndex];
              return `${row.topic}: 样本 ${row.count} / P50 ${compact(row.p50)} / P90 ${compact(row.p90)}`;
            }
          }
        }
      },
      scales: {
        x: { title: { display: true, text: "话题供给数量" }, beginAtZero: true },
        y: { type: "logarithmic", title: { display: true, text: "话题中位播放（对数）" }, ticks: { callback: compact } }
      }
    })
  });

  const industryStats = [...derived.industryStats].sort((a, b) => b.count - a.count);
  drawChart("guestPerformanceChart", {
    type: "bar",
    data: {
      labels: industryStats.map((d) => d.industry),
      datasets: [
        { label: "P50", data: industryStats.map((d) => Math.round(d.p50)), backgroundColor: palette[5], borderRadius: 5 },
        { label: "P90", data: industryStats.map((d) => Math.round(d.p90)), backgroundColor: palette[7], borderRadius: 5 }
      ]
    },
    options: baseOptions({
      indexAxis: "y",
      scales: {
        x: { ticks: { callback: compact }, grid: { color: "#eef2f6" } },
        y: { grid: { display: false } }
      },
      plugins: {
        legend: { labels: { boxWidth: 12, color: "#18202a" } },
        tooltip: {
          callbacks: {
            afterBody: (items) => {
              const row = industryStats[items[0].dataIndex];
              return `样本数：${row.count}`;
            }
          }
        }
      }
    })
  });
}

function renderHitRows(videos) {
  document.getElementById("hitRows").innerHTML = videos
    .map((video) => `
      <tr>
        <td><a href="${video.url}" target="_blank" rel="noreferrer">${video.title}</a></td>
        <td>${video.channelTitle}</td>
        <td>${compact(video.viewCount)}</td>
        <td>${video.durationLabel}</td>
        <td>${video.topic}</td>
        <td>${video.guestIndustry}</td>
        <td><div class="tag-list">${(video.hitReasons || []).map((reason) => `<span class="tag">${reason}</span>`).join("")}</div></td>
      </tr>
    `)
    .join("");
}

function renderChannelRows(channels) {
  document.getElementById("channelRows").innerHTML = channels
    .map((channel) => `
      <tr>
        <td><a href="${channel.url || channel.source_url || "#"}" target="_blank" rel="noreferrer">${channel.title}</a></td>
        <td>${compact(channel.subscriberCount)}</td>
        <td>${compact(channel.viewCount)}</td>
        <td>${compact(channel.sampleVideoCount)}</td>
        <td>${compact(channel.sampleMedianViews)}</td>
        <td>${channel.subscriberGrowth === null ? "--" : compact(channel.subscriberGrowth)}</td>
      </tr>
    `)
    .join("");
}

function renderAdvice(data) {
  document.getElementById("positioningAdvice").innerHTML = data.recommendations.positioning.map((text) => `<p>${text}</p>`).join("");
  document.getElementById("avoidAdvice").innerHTML = data.recommendations.avoid.map((text) => `<p>${text}</p>`).join("");
  document.getElementById("methodology").textContent = data.methodology;
  document.getElementById("sources").innerHTML = (data.sources || [])
    .map((source) => `<a href="${source.url}" target="_blank" rel="noreferrer">${source.title}</a>`)
    .join("");
}

async function main() {
  const data = await loadDashboardData();
  const derived = computeDerived(data);
  setText("snapshotMode", data.snapshot_mode === "live" ? "Live 最新快照" : "Demo 演示快照");
  setText("generatedAt", dateText(data.generated_at));
  document.getElementById("modeNotice").textContent =
    data.snapshot_mode === "live"
      ? "当前页面展示 GitHub Actions 生成的 YouTube 数据快照。频道竞争图已过滤无有效样本频道，并使用双对数尺度处理离群点。"
      : "当前页面为演示快照。配置 YOUTUBE_API_KEY 后，每天会自动拉取 YouTube 最新数据并更新分析。";
  renderMetrics(data, derived);
  renderCoreCharts(data, derived);
  renderResearchCharts(data, derived);
  renderHitRows(data.summary.hitVideos);
  renderChannelRows(data.channels);
  renderAdvice(data);
}

main().catch((error) => {
  document.body.innerHTML = `<main><section class="notice">数据加载失败：${error.message}</section></main>`;
});

async function loadDashboardData() {
  const candidates = [
    "data/latest.json",
    "./data/latest.json",
    "../data/latest.json",
    "site/data/latest.json",
    "./site/data/latest.json"
  ];
  const errors = [];
  for (const url of candidates) {
    try {
      const response = await fetch(`${url}?v=${Date.now()}`, { cache: "no-store" });
      const text = await response.text();
      if (!response.ok) {
        errors.push(`${url}: HTTP ${response.status}`);
        continue;
      }
      const trimmed = text.trim();
      if (!trimmed.startsWith("{")) {
        errors.push(`${url}: 返回的不是 JSON`);
        continue;
      }
      return JSON.parse(trimmed);
    } catch (error) {
      errors.push(`${url}: ${error.message}`);
    }
  }
  throw new Error(`没有找到可用的数据快照。请确认已上传 site/data/latest.json 或 data/latest.json。${errors.join("；")}`);
}
