"use strict";
(self.webpackChunkmi_account = self.webpackChunkmi_account || []).push([[7634], {
    23963: function(n, e, t) {
        t.r(e),
        t.d(e, {
            encryptAes: function() {
                return Q
            },
            rsa: function() {
                return B
            }
        });
        t(85005),
        t(80044),
        t(10853),
        t(6208),
        t(33290),
        t(55862);
        var o = t(78177)
          , r = t.n(o)
          , a = t(10886)
          , c = t.n(a)
          , i = t(12440)
          , A = t.n(i)
          , I = t(695);
        function Q(n) {
            n = n || {};
            var e = function(n) {
                for (var e = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*", t = "", o = 0; o < n; o++) {
                    var r = Math.floor(Math.random() * e.length);
                    t += e.substring(r, r + 1)
                }
                return t
            }(16)
              , t = "account.preview.n.xiaomi.net" === window.location.host
              , o = new I.X({});
            o.setPublicKey(t ? "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC0gABHEoaFAcUPlaqKFn3mOOdQ7m5SIINJ0+dLo6hq4AcGAJKnYP+uM1Ge0++8SVxPBC2H+AYBiaeYC0UC5El9fAdGRWjRt2QdDqY0GeB3iPoEAiNvTPgcjKXjt7++fb0CQ2yY9My13py2glTTENCEhD64bjW8n1/9zUrq5XJv7wIDAQAB" : "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCYEVrK/4Mahiv0pUJgTybx4J9P5dUT/Y0PuwMbk+gMU+jrZnBiXGv6/hCH1avIhoBcE535F8nJQQN3UavZdFkYidsoXuEnat3+eVTp3FslyhRwIBDF09v4vDhRtxFOT+R7uH7h/mzmyA2/+lfIMWGIrffXprYizbV76+YQKhoqFQIDAQAB");
            var a = o.encrypt(window.btoa(e))
              , i = c().parse("0102030405060708")
              , Q = c().parse(e)
              , B = window.btoa(Object.keys(n).join(","))
              , u = {};
            return Object.keys(n).forEach((function(e) {
                var t = n[e]
                  , o = r().encrypt(t, Q, {
                    iv: i,
                    padding: A()
                });
                o = o.toString(),
                u[e] = o
            }
            )),
            {
                EUI: "".concat(a, ".").concat(B),
                encryptedParams: u
            }
        }
        function B(n) {
            var e = new I.X({})
              , t = {}
              , o = "account.preview.n.xiaomi.net" === window.location.host;
            return Object.keys(n).forEach((function(r) {
                var a = n[r];
                e.setPublicKey(o ? "-----BEGIN PUBLIC KEY-----MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC1Wv68Hb+Ptbl+skk07KQc8teeBRVZO1wX0V9W2kdkYEZP0Wez1AAJXLiFPfZ5Xbper6DTz51mo3EoS7bJhaX7f7ispnyPZ7gAj/3f/sbNmJIOU7MYcHUNHlagr552VgvIPTpry+weHTDwoUIIn+n7Pr0IEnV65gWI5tT8NARWrQIDAQAB-----END PUBLIC KEY-----" : "-----BEGIN PUBLIC KEY-----MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCHcPEm9Wo8/LWHL8mohOV5YalTgZLzng+nWCEkIRP//6GohYlIh3dvGpueJvQ3Sany/3dLx0x6MQKA34NxRyoO37R/LgPZUfe6eWzHQeColBBHxTEDbCqDh46Gv5vogjqHRl4+q2WGCmZOIfmPjNHQWG8sMIZyTqFCLc6gk9vSewIDAQAB-----END PUBLIC KEY-----"),
                t[r] = e.encrypt(a)
            }
            )),
            {
                encryptedParams: t
            }
        }
    }
}]);
