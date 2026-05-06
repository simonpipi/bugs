97815: function(e, t, o) {
            "use strict";
            var a = o(41034)
              , n = (o(44114),
            o(26910),
            o(62953),
            o(21396))
              , i = o.n(n);
            const r = "key"
              , l = (e={}, t) => {
                const o = (0,
                a.A)({}, e);
                Object.keys(o).forEach((e => {
                    "" === o[e] && delete o[e]
                }
                ));
                const n = Object.keys(o).sort().filter((e => !(void 0 === o[e])));
                n.push(r),
                o[r] = t;
                const l = `${n.map((e => `${e}=${o[e]}`)).join("&")}`;
                return [i().MD5(l).toString(i().enc.Hex), n.join(",")]
            }
              , s = (e, t, o, n, i, r, s, c) => {
                const d = (0,
                a.A)({
                    product: n,
                    appVersion: s || "12.0.0",
                    client: c || "web",
                    mid: 1,
                    vendor: "web",
                    screen: 1,
                    model: 1,
                    imei: 1,
                    network: "wifi",
                    keyfrom: i || "fanyi.web",
                    keyid: o,
                    mysticTime: Date.now(),
                    yduuid: r || "abcdefg",
                    abtest: 0
                }, e)
                  , [u,p] = l(d, t);
                return Object.assign(d, {
                    sign: u,
                    pointParam: p
                }),
                d
            }
              , c = (e, t, o, n, i, r, s, c) => {
                const d = (0,
                a.A)({
                    product: n,
                    appVersion: s || "12.0.0",
                    client: c || "web",
                    mid: 1,
                    vendor: "web",
                    screen: 1,
                    model: 1,
                    imei: 1,
                    network: "wifi",
                    keyfrom: i || "fanyi.web",
                    keyid: o,
                    mysticTime: Date.now(),
                    yduuid: r || "abcdefg",
                    abtest: 0
                }, e)
                  , [u,p] = l(d, t);
                Object.assign(d, {
                    sign: u,
                    pointParam: p
                });
                const m = new FormData
                  , g = Object.keys(d);
                return g.forEach((e => {
                    m.append(e, d[e])
                }
                )),
                console.log("requestData", m),
                m
            }
              , d = (e, t, o, n, i, r, s, c, d) => {
                const u = (0,
                a.A)({
                    product: i,
                    appVersion: c || "12.0.0",
                    client: d || "web",
                    mid: 1,
                    vendor: "web",
                    screen: 1,
                    model: 1,
                    imei: 1,
                    network: "wifi",
                    keyfrom: r || "fanyi.web",
                    keyid: n,
                    mysticTime: Date.now(),
                    yduuid: s || "abcdefg",
                    abtest: 0
                }, t)
                  , [p,m] = l(u, o);
                Object.assign(u, (0,
                a.A)({
                    sign: p,
                    pointParam: m
                }, e));
                const g = new FormData
                  , h = Object.keys(u);
                return h.forEach((e => {
                    g.append(e, u[e])
                }
                )),
                console.log("requestData", g),
                g
            }
            ;
            t.A = {
                genSign: l,
                genParamV3: s,
                genParamV3FormData: c,
                genParamV3FormDataWithNormalParam: d
            }
        },