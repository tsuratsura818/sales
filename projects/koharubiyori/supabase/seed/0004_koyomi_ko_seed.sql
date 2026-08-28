-- =============================================================
-- 0004_koyomi_ko_seed.sql
-- 七十二候マスタの投入（本朝七十二候・立春はじまり）
--
-- ・copy 列（候のコピー）は意図的に埋めていない。文はここではなく
--   管理画面／SQL で後から入れる。再実行しても copy を消さないよう
--   on conflict では copy を更新しない。
-- ・slug は掛け紙の印刷物と URL に直結する。ここを唯一の正とし、
--   コード内でローマ字を組み立てないこと（CLAUDE.md §9）。
-- ・starts_md は 'MM-DD'。年をまたぐので日付型にしない。
--   節気の日付は年により±1日ずれるが、候の切り替わりは
--   この表を運用上の基準とする。
-- =============================================================

insert into koharubiyori.koyomi_ko (id, slug, name, reading, sekki, starts_md) values
  ( 1, 'harukaze-kori-o-toku',            '東風解凍', 'はるかぜこおりをとく',           '立春', '02-04'),
  ( 2, 'uguisu-naku',                     '黄鶯睍睆', 'うぐいすなく',                   '立春', '02-09'),
  ( 3, 'uo-kori-o-izuru',                 '魚上氷',   'うおこおりをいずる',             '立春', '02-14'),
  ( 4, 'tsuchi-no-sho-uruoi-okoru',       '土脉潤起', 'つちのしょううるおいおこる',     '雨水', '02-19'),
  ( 5, 'kasumi-hajimete-tanabiku',        '霞始靆',   'かすみはじめてたなびく',         '雨水', '02-24'),
  ( 6, 'somoku-mebae-izuru',              '草木萌動', 'そうもくめばえいずる',           '雨水', '03-01'),
  ( 7, 'sugomori-mushi-to-o-hiraku',      '蟄虫啓戸', 'すごもりむしとをひらく',         '啓蟄', '03-06'),
  ( 8, 'momo-hajimete-saku',              '桃始笑',   'ももはじめてさく',               '啓蟄', '03-11'),
  ( 9, 'namushi-cho-to-naru',             '菜虫化蝶', 'なむしちょうとなる',             '啓蟄', '03-16'),
  (10, 'suzume-hajimete-sukuu',           '雀始巣',   'すずめはじめてすくう',           '春分', '03-21'),
  (11, 'sakura-hajimete-hiraku',          '桜始開',   'さくらはじめてひらく',           '春分', '03-26'),
  (12, 'kaminari-sunawachi-koe-o-hassu',  '雷乃発声', 'かみなりすなわちこえをはっす',   '春分', '03-31'),
  (13, 'tsubame-kitaru',                  '玄鳥至',   'つばめきたる',                   '清明', '04-05'),
  (14, 'kogan-kaeru',                     '鴻雁北',   'こうがんかえる',                 '清明', '04-10'),
  (15, 'niji-hajimete-arawaru',           '虹始見',   'にじはじめてあらわる',           '清明', '04-15'),
  (16, 'ashi-hajimete-shozu',             '葭始生',   'あしはじめてしょうず',           '穀雨', '04-20'),
  (17, 'shimo-yamite-nae-izuru',          '霜止出苗', 'しもやみてなえいずる',           '穀雨', '04-25'),
  (18, 'botan-hana-saku',                 '牡丹華',   'ぼたんはなさく',                 '穀雨', '04-30'),
  (19, 'kawazu-hajimete-naku',            '蛙始鳴',   'かわずはじめてなく',             '立夏', '05-05'),
  (20, 'mimizu-izuru',                    '蚯蚓出',   'みみずいずる',                   '立夏', '05-10'),
  (21, 'takenoko-shozu',                  '竹笋生',   'たけのこしょうず',               '立夏', '05-15'),
  (22, 'kaiko-okite-kuwa-o-hamu',         '蚕起食桑', 'かいこおきてくわをはむ',         '小満', '05-21'),
  (23, 'benibana-sakau',                  '紅花栄',   'べにばなさかう',                 '小満', '05-26'),
  (24, 'mugi-no-toki-itaru',              '麦秋至',   'むぎのときいたる',               '小満', '05-31'),
  (25, 'kamakiri-shozu',                  '螳螂生',   'かまきりしょうず',               '芒種', '06-06'),
  (26, 'kusaretaru-kusa-hotaru-to-naru',  '腐草為蛍', 'くされたるくさほたるとなる',     '芒種', '06-11'),
  (27, 'ume-no-mi-kibamu',                '梅子黄',   'うめのみきばむ',                 '芒種', '06-16'),
  (28, 'natsukarekusa-karuru',            '乃東枯',   'なつかれくさかるる',             '夏至', '06-21'),
  (29, 'ayame-hana-saku',                 '菖蒲華',   'あやめはなさく',                 '夏至', '06-27'),
  (30, 'hange-shozu',                     '半夏生',   'はんげしょうず',                 '夏至', '07-02'),
  (31, 'atsukaze-itaru',                  '温風至',   'あつかぜいたる',                 '小暑', '07-07'),
  (32, 'hasu-hajimete-hiraku',            '蓮始開',   'はすはじめてひらく',             '小暑', '07-12'),
  (33, 'taka-sunawachi-waza-o-narau',     '鷹乃学習', 'たかすなわちわざをならう',       '小暑', '07-18'),
  (34, 'kiri-hajimete-hana-o-musubu',     '桐始結花', 'きりはじめてはなをむすぶ',       '大暑', '07-23'),
  (35, 'tsuchi-uruote-mushi-atsushi',     '土潤溽暑', 'つちうるおうてむしあつし',       '大暑', '07-28'),
  (36, 'taiu-tokidoki-furu',              '大雨時行', 'たいうときどきふる',             '大暑', '08-02'),
  (37, 'suzukaze-itaru',                  '涼風至',   'すずかぜいたる',                 '立秋', '08-08'),
  (38, 'higurashi-naku',                  '寒蝉鳴',   'ひぐらしなく',                   '立秋', '08-13'),
  (39, 'fukaki-kiri-matou',               '蒙霧升降', 'ふかききりまとう',               '立秋', '08-18'),
  (40, 'wata-no-hana-shibe-hiraku',       '綿柎開',   'わたのはなしべひらく',           '処暑', '08-23'),
  (41, 'tenchi-hajimete-samushi',         '天地始粛', 'てんちはじめてさむし',           '処暑', '08-28'),
  (42, 'kokumono-sunawachi-minoru',       '禾乃登',   'こくものすなわちみのる',         '処暑', '09-02'),
  (43, 'kusa-no-tsuyu-shiroshi',          '草露白',   'くさのつゆしろし',               '白露', '09-08'),
  (44, 'sekirei-naku',                    '鶺鴒鳴',   'せきれいなく',                   '白露', '09-13'),
  (45, 'tsubame-saru',                    '玄鳥去',   'つばめさる',                     '白露', '09-18'),
  (46, 'kaminari-sunawachi-koe-o-osamu',  '雷乃収声', 'かみなりすなわちこえをおさむ',   '秋分', '09-23'),
  (47, 'mushi-kakurete-to-o-fusagu',      '蟄虫坏戸', 'むしかくれてとをふさぐ',         '秋分', '09-28'),
  (48, 'mizu-hajimete-karuru',            '水始涸',   'みずはじめてかるる',             '秋分', '10-03'),
  (49, 'kogan-kitaru',                    '鴻雁来',   'こうがんきたる',                 '寒露', '10-08'),
  (50, 'kiku-no-hana-hiraku',             '菊花開',   'きくのはなひらく',               '寒露', '10-13'),
  (51, 'kirigirisu-to-ni-ari',            '蟋蟀在戸', 'きりぎりすとにあり',             '寒露', '10-18'),
  (52, 'shimo-hajimete-furu',             '霜始降',   'しもはじめてふる',               '霜降', '10-23'),
  (53, 'kosame-tokidoki-furu',            '霎時施',   'こさめときどきふる',             '霜降', '10-28'),
  (54, 'momiji-tsuta-kibamu',             '楓蔦黄',   'もみじつたきばむ',               '霜降', '11-02'),
  (55, 'tsubaki-hajimete-hiraku',         '山茶始開', 'つばきはじめてひらく',           '立冬', '11-07'),
  (56, 'chi-hajimete-koru',               '地始凍',   'ちはじめてこおる',               '立冬', '11-12'),
  (57, 'kinsenka-saku',                   '金盞香',   'きんせんかさく',                 '立冬', '11-17'),
  (58, 'niji-kakurete-miezu',             '虹蔵不見', 'にじかくれてみえず',             '小雪', '11-22'),
  (59, 'kitakaze-konoha-o-harau',         '朔風払葉', 'きたかぜこのはをはらう',         '小雪', '11-27'),
  (60, 'tachibana-hajimete-kibamu',       '橘始黄',   'たちばなはじめてきばむ',         '小雪', '12-02'),
  (61, 'sora-samuku-fuyu-to-naru',        '閉塞成冬', 'そらさむくふゆとなる',           '大雪', '12-07'),
  (62, 'kuma-ana-ni-komoru',              '熊蟄穴',   'くまあなにこもる',               '大雪', '12-12'),
  (63, 'sake-no-uo-muragaru',             '鱖魚群',   'さけのうおむらがる',             '大雪', '12-16'),
  (64, 'natsukarekusa-shozu',             '乃東生',   'なつかれくさしょうず',           '冬至', '12-22'),
  (65, 'sawashika-no-tsuno-otsuru',       '麋角解',   'さわしかのつのおつる',           '冬至', '12-26'),
  (66, 'yuki-watarite-mugi-nobiru',       '雪下出麦', 'ゆきわたりてむぎのびる',         '冬至', '12-31'),
  (67, 'seri-sunawachi-sakau',            '芹乃栄',   'せりすなわちさかう',             '小寒', '01-05'),
  (68, 'shimizu-atatakao-fukumu',         '水泉動',   'しみずあたたかをふくむ',         '小寒', '01-10'),
  (69, 'kiji-hajimete-naku',              '雉始雊',   'きじはじめてなく',               '小寒', '01-15'),
  (70, 'fuki-no-hana-saku',               '款冬華',   'ふきのはなさく',                 '大寒', '01-20'),
  (71, 'sawamizu-kori-tsumeru',           '水沢腹堅', 'さわみずこおりつめる',           '大寒', '01-25'),
  (72, 'niwatori-hajimete-toya-ni-tsuku', '鶏始乳',   'にわとりはじめてとやにつく',     '大寒', '01-30')
on conflict (id) do update set
  slug      = excluded.slug,
  name      = excluded.name,
  reading   = excluded.reading,
  sekki     = excluded.sekki,
  starts_md = excluded.starts_md;
  -- copy は更新しない。後から入れた候のコピーを再実行で消さないため
